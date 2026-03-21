from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

from pygls.lsp.server import LanguageServer
from lsprotocol.types import Hover, HoverParams, InitializeParams, MarkupContent, MarkupKind

INITIALIZE = "initialize"
TEXT_DOCUMENT_HOVER = "textDocument/hover"

RAG_DB = Path("build/rag.db")
RTL_JSON = Path("build/rtl_ast.json")
GRAPH_JSON = Path("build/causal_graph.json")

_SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"


def _neo4j_causal_for_signal(module: str, signal: str) -> dict:
    """Query Neo4j for 1-hop context. Returns {"drivers": [...], "dependents": [...]}."""
    try:
        if str(_SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(_SCRIPTS_DIR))
        from neo4j_query import get_causal_context  # type: ignore
        ctx = get_causal_context(module, [signal])
        entry = ctx.get(signal, {})
        return {
            "drivers": entry.get("drivers", []),
            "dependents": entry.get("dependents", []),
        }
    except Exception as exc:  # noqa: BLE001
        warnings.warn(f"[lsp] Neo4j not reachable: {exc}", stacklevel=2)
        return {"drivers": [], "dependents": []}


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
                    if neo4j_ctx["drivers"]:
                        suffix_parts.append(f"driven by: {neo4j_ctx['drivers'][0]}")
                    if neo4j_ctx["dependents"]:
                        suffix_parts.append(f"drives: {neo4j_ctx['dependents'][0]}")
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


@ls.command(RtlAiLanguageServer.CMD_GET_CONTEXT)
def get_context(ls: RtlAiLanguageServer, *args, **kwargs):  # noqa: ANN001
    symbol = kwargs.get("symbol")
    response = {"symbol": symbol, "edges": [], "neo4j_context": None}
    if symbol:
        for graph in ls.graphs:
            for edge in graph.get("edges", []):
                if edge["from"] == symbol or edge["to"] == symbol:
                    response["edges"].append(edge)
        # Neo4j real-time context
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
