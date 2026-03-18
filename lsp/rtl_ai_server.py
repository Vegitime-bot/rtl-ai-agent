from __future__ import annotations

import json
from pathlib import Path

from pygls.lsp.server import LanguageServer
from lsprotocol.types import Hover, HoverParams, InitializeParams, MarkupContent, MarkupKind

INITIALIZE = "initialize"
TEXT_DOCUMENT_HOVER = "textDocument/hover"

RAG_DB = Path("build/rag.db")
RTL_JSON = Path("build/rtl_ast.json")
GRAPH_JSON = Path("build/causal_graph.json")


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
                summary = f"{signal['name']} : {signal['type']} {signal['width']}"
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
    response = {"symbol": symbol, "edges": []}
    if symbol:
        for graph in ls.graphs:
            for edge in graph.get("edges", []):
                if edge["from"] == symbol or edge["to"] == symbol:
                    response["edges"].append(edge)
    return response


if __name__ == "__main__":
    ls.start_io()
