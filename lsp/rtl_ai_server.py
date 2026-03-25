from __future__ import annotations

import json
import re
import sys
import warnings
from pathlib import Path
from urllib.parse import unquote, urlparse

from pygls.lsp.server import LanguageServer
from lsprotocol.types import (
    Diagnostic,
    DiagnosticSeverity,
    DidOpenTextDocumentParams,
    DidSaveTextDocumentParams,
    Hover,
    HoverParams,
    InitializeParams,
    MarkupContent,
    MarkupKind,
    Position,
    Range,
    RenameParams,
    TextEdit,
    WorkspaceEdit,
)

INITIALIZE = "initialize"
TEXT_DOCUMENT_HOVER = "textDocument/hover"
TEXT_DOCUMENT_DID_OPEN = "textDocument/didOpen"
TEXT_DOCUMENT_DID_SAVE = "textDocument/didSave"
TEXT_DOCUMENT_RENAME = "textDocument/rename"

# FAISS 인덱스 경로 (구형 RAG_DB = Path("build/rag.db") — FAISS로 전환됨)
FAISS_INDEX = Path("build/faiss_index")
RTL_JSON = Path("build/rtl_ast.json")
GRAPH_JSON = Path("build/causal_graph.json")

_SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
_ORCHESTRATOR_DIR = Path(__file__).parent.parent / "orchestrator"


def _uri_to_path(uri: str) -> Path:
    """Convert a file:// URI to a filesystem Path."""
    parsed = urlparse(uri)
    return Path(unquote(parsed.path))


def _neo4j_causal_for_signal(module: str, signal: str) -> dict:
    """Query Neo4j for 2-hop context. Returns drivers/dependents with hop metadata."""
    try:
        if str(_SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(_SCRIPTS_DIR))
        from neo4j_query import get_causal_context_nhop  # type: ignore
        ctx = get_causal_context_nhop(module, [signal], n_hops=2)
        entry = ctx.get(signal, {})
        return {
            "drivers": entry.get("drivers", []),
            "dependents": entry.get("dependents", []),
            "driver_hops": entry.get("driver_hops", {}),
            "dependent_hops": entry.get("dependent_hops", {}),
        }
    except Exception as exc:  # noqa: BLE001
        warnings.warn(f"[lsp] Neo4j not reachable: {exc}", stacklevel=2)
        return {"drivers": [], "dependents": [], "driver_hops": {}, "dependent_hops": {}}


def _format_2hop(names: list, hops: dict, upstream: bool) -> str:
    """Format signal list with 2-hop arrow notation: A → B."""
    if not names:
        return ""
    hop1 = [n for n in names if hops.get(n, 1) == 1]
    hop2 = [n for n in names if hops.get(n, 1) == 2]
    if upstream:
        # causal chain: hop2_sources → hop1_sources → signal
        segments = []
        if hop2:
            segments.append(", ".join(hop2[:2]))
        if hop1:
            segments.append(", ".join(hop1[:2]))
        return " → ".join(segments) if segments else ", ".join(names[:2])
    else:
        # causal chain: signal → hop1_targets → hop2_targets
        segments = []
        if hop1:
            segments.append(", ".join(hop1[:2]))
        if hop2:
            segments.append(", ".join(hop2[:2]))
        return " → ".join(segments) if segments else ", ".join(names[:2])


class RtlAiLanguageServer(LanguageServer):
    CMD_GET_CONTEXT = "rtl-ai/getContext"

    def __init__(self):
        super().__init__("rtl-ai-server", "0.1")
        self.modules = []
        self.graphs = []

    def load_data(self) -> None:
        if RTL_JSON.exists():
            self.modules = json.loads(RTL_JSON.read_text()).get("modules", [])
        if GRAPH_JSON.exists():
            self.graphs = json.loads(GRAPH_JSON.read_text()).get("graphs", [])

    def _find_signal_module(self, signal_name: str) -> str | None:
        """Return the RTL module name that owns this signal, or None."""
        for module in self.modules:
            for sig in module.get("signals", []):
                if sig["name"] == signal_name:
                    return module.get("name")
        return None


ls = RtlAiLanguageServer()


@ls.feature(INITIALIZE)
def _(*params: InitializeParams):  # noqa: ANN001
    ls.load_data()
    return None


# ─────────────────────────────────────────────
# publishDiagnostics — verify.py 연동
# ─────────────────────────────────────────────

def _run_verify_diagnostics(ls: RtlAiLanguageServer, uri: str) -> None:
    """Run verify checks on uri and publish LSP diagnostics to the client."""
    if not uri.endswith(".v"):
        ls.publish_diagnostics(uri, [])
        return

    rtl_path = _uri_to_path(uri)
    if not rtl_path.exists():
        return

    if str(_ORCHESTRATOR_DIR) not in sys.path:
        sys.path.insert(0, str(_ORCHESTRATOR_DIR))
    try:
        from verify import run_checks  # type: ignore
    except ImportError as exc:
        warnings.warn(f"[lsp] cannot import verify: {exc}", stacklevel=2)
        return

    result = run_checks(rtl_path, causal_graph_path=GRAPH_JSON if GRAPH_JSON.exists() else None)
    file_lines = rtl_path.read_text().splitlines()
    diagnostics: list[Diagnostic] = []

    # basic 검증 결과
    basic = result["results"].get("basic", {})
    if basic.get("status") == "fail":
        detail = basic.get("detail", "verification failed")
        line_num = 0
        if "TODO" in detail:
            for i, line in enumerate(file_lines):
                if "TODO" in line:
                    line_num = i
                    break
        severity = DiagnosticSeverity.Warning if "TODO" in detail else DiagnosticSeverity.Error
        diagnostics.append(Diagnostic(
            range=Range(
                start=Position(line=line_num, character=0),
                end=Position(line=line_num, character=0),
            ),
            message=detail,
            severity=severity,
        ))

    # causal 검증 결과 — missing edge마다 신호 위치 매핑
    causal = result["results"].get("causal", {})
    if causal.get("status") == "fail":
        for edge_str in causal.get("missing_edges", []):
            line_num = 0
            m = re.match(r'(\w+)\s*[→>-]+\s*(\w+)', edge_str)
            if m:
                signal = m.group(1)
                for i, line in enumerate(file_lines):
                    if re.search(r'\b' + re.escape(signal) + r'\b', line):
                        line_num = i
                        break
            diagnostics.append(Diagnostic(
                range=Range(
                    start=Position(line=line_num, character=0),
                    end=Position(line=line_num, character=0),
                ),
                message=f"Missing causal edge: {edge_str}",
                severity=DiagnosticSeverity.Error,
            ))

    ls.publish_diagnostics(uri, diagnostics)


@ls.feature(TEXT_DOCUMENT_DID_OPEN)
def did_open(ls: RtlAiLanguageServer, params: DidOpenTextDocumentParams) -> None:
    _run_verify_diagnostics(ls, params.text_document.uri)


@ls.feature(TEXT_DOCUMENT_DID_SAVE)
def did_save(ls: RtlAiLanguageServer, params: DidSaveTextDocumentParams) -> None:
    _run_verify_diagnostics(ls, params.text_document.uri)


# ─────────────────────────────────────────────
# textDocument/hover — 2-hop Neo4j 확장
# ─────────────────────────────────────────────

@ls.feature(TEXT_DOCUMENT_HOVER)
def hover(ls: RtlAiLanguageServer, params: HoverParams) -> Hover | None:
    word = ls.workspace.get_document(params.text_document.uri).word_at_position(params.position)
    if not word:
        return None
    summary = None
    for module in ls.modules:
        for signal in module.get("signals", []):
            if signal["name"] == word:
                base = f"{signal['name']} : {signal['type']} {signal['width']}"
                module_name = module.get("name")
                if module_name:
                    neo4j_ctx = _neo4j_causal_for_signal(module_name, word)
                    suffix_parts = []
                    driven = _format_2hop(
                        neo4j_ctx["drivers"], neo4j_ctx["driver_hops"], upstream=True
                    )
                    drives = _format_2hop(
                        neo4j_ctx["dependents"], neo4j_ctx["dependent_hops"], upstream=False
                    )
                    if driven:
                        suffix_parts.append(f"driven by: {driven}")
                    if drives:
                        suffix_parts.append(f"drives: {drives}")
                    if suffix_parts:
                        base += " | " + ", ".join(suffix_parts)
                summary = base
                break
        if summary:
            break
    if not summary:
        return None
    content = MarkupContent(kind=MarkupKind.PlainText, value=summary)
    return Hover(contents=content)


# ─────────────────────────────────────────────
# textDocument/rename — workspace 전체 .v 파일 지원
# ─────────────────────────────────────────────

@ls.feature(TEXT_DOCUMENT_RENAME)
def rename(ls: RtlAiLanguageServer, params: RenameParams) -> WorkspaceEdit | None:
    doc = ls.workspace.get_document(params.text_document.uri)
    old_name = doc.word_at_position(params.position)
    if not old_name:
        return None

    new_name = params.new_name
    changes: dict[str, list[TextEdit]] = {}

    # workspace root에서 모든 .v 파일 수집
    v_files: list[Path] = []
    try:
        root_uri = ls.workspace.root_uri
        if root_uri:
            v_files = list(_uri_to_path(root_uri).rglob("*.v"))
    except Exception:
        pass

    current_path = _uri_to_path(params.text_document.uri)
    if current_path not in v_files:
        v_files.append(current_path)

    for v_file in v_files:
        try:
            lines = v_file.read_text().splitlines()
        except Exception:
            continue
        edits: list[TextEdit] = []
        for line_num, line in enumerate(lines):
            for m in re.finditer(r'\b' + re.escape(old_name) + r'\b', line):
                edits.append(TextEdit(
                    range=Range(
                        start=Position(line=line_num, character=m.start()),
                        end=Position(line=line_num, character=m.end()),
                    ),
                    new_text=new_name,
                ))
        if edits:
            changes[v_file.as_uri()] = edits

    return WorkspaceEdit(changes=changes) if changes else None


# ─────────────────────────────────────────────
# rtl-ai/getContext command
# ─────────────────────────────────────────────

@ls.command(RtlAiLanguageServer.CMD_GET_CONTEXT)
def get_context(ls: RtlAiLanguageServer, *args, **kwargs):  # noqa: ANN001
    symbol = kwargs.get("symbol")
    response = {"symbol": symbol, "edges": [], "neo4j_context": None}
    if symbol:
        for graph in ls.graphs:
            for edge in graph.get("edges", []):
                if edge["from"] == symbol or edge["to"] == symbol:
                    response["edges"].append(edge)
        # Neo4j real-time 2-hop context
        module_name = ls._find_signal_module(symbol)
        if not module_name:
            for graph in ls.graphs:
                if graph.get("module"):
                    module_name = graph["module"]
                    break
        if module_name:
            response["neo4j_context"] = _neo4j_causal_for_signal(module_name, symbol)
    return response


if __name__ == "__main__":
    ls.start_io()
