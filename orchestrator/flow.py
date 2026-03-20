#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import warnings
from pathlib import Path

from agents.plan_agent import build_plan
from agents.report_agent import write_report
from agents.spec_agent import analyze
from codegen import generate_rtl
from llm_utils import call_llm, load_model_config
from verify import run_checks


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text())


def query_chunks(conn: sqlite3.Connection, keyword: str) -> list[dict]:
    cur = conn.execute(
        "SELECT kind, ref, content FROM chunks WHERE content LIKE ?",
        (f"%{keyword}%",),
    )
    return [dict(zip(["kind", "ref", "content"], row)) for row in cur.fetchall()]


_SIGNAL_RE = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]{1,63})\b")
_STOP_WORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "in", "on", "at", "to",
    "of", "and", "or", "not", "for", "with", "from", "that", "this",
    "module", "signal", "logic", "reg", "wire", "input", "output",
    "always", "assign", "begin", "end", "if", "else", "case",
})


def _extract_signals(texts: list[str]) -> list[str]:
    """Heuristically extract Verilog-style identifiers from free-text strings."""
    seen: dict[str, int] = {}
    for text in texts:
        for m in _SIGNAL_RE.finditer(text):
            tok = m.group(1)
            if tok.lower() not in _STOP_WORDS and not tok[0].isupper():
                seen[tok] = seen.get(tok, 0) + 1
    # Return identifiers that appear at least once, sorted by frequency desc
    return [k for k, _ in sorted(seen.items(), key=lambda x: -x[1])]


def _query_neo4j_context(module: str, signals: list[str]) -> str:
    """Query Neo4j for causal context; return formatted string or empty string on failure."""
    try:
        scripts_dir = Path(__file__).parent.parent / "scripts"
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        from neo4j_query import get_causal_context, format_graph_context  # type: ignore
        ctx = get_causal_context(module, signals)
        return format_graph_context(ctx)
    except Exception as exc:  # noqa: BLE001
        warnings.warn(f"[flow] Neo4j not reachable, skipping graph context: {exc}", stacklevel=2)
        return ""


def summarize_graphs(data: dict) -> list[str]:
    notes: list[str] = []
    for graph in data.get("graphs", []):
        for edge in graph.get("edges", [])[:5]:
            notes.append(f"{graph['module']}: {edge['from']} -> {edge['to']} ({edge['kind']})")
    return notes




def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", default="demo")
    parser.add_argument("--db", default="build/rag.db")
    parser.add_argument("--out", default="outputs/analysis.md")
    parser.add_argument("--model-config", type=Path)
    parser.add_argument("--origin-rtl", type=Path, default=Path("inputs/origin.v"))
    parser.add_argument("--uarch-origin", type=Path, default=Path("inputs/uArch_origin.txt"))
    parser.add_argument("--uarch-new", type=Path, default=Path("inputs/uArch_new.txt"))
    parser.add_argument("--algo-origin", type=Path, default=Path("inputs/algorithm_origin.py"))
    parser.add_argument("--algo-new", type=Path, default=Path("inputs/algorithm_new.py"))
    parser.add_argument("--generate-rtl", action="store_true")
    parser.add_argument("--output-rtl", type=Path, default=Path("outputs/new.v"))
    args = parser.parse_args()

    build_dir = Path("build")
    rtl_data = load_json(build_dir / "rtl_ast.json")
    pseudo_diff = load_json(build_dir / "pseudo_diff.json")["diff"]
    graph_path = build_dir / "causal_graph.json"
    graph_data = load_json(graph_path) if graph_path.exists() else {"graphs": []}
    conn = sqlite3.connect(args.db)
    ma_chunks = [c for c in query_chunks(conn, args.ip) if c["kind"] == "ma"]

    findings = analyze(ma_chunks, "\n".join(pseudo_diff))
    graph_notes = summarize_graphs(graph_data)
    plan = build_plan(rtl_data.get("modules", []), [f.summary for f in findings], graph_notes)

    # --- Neo4j graph context injection ---
    module_names = list({g.get("module") for g in graph_data.get("graphs", []) if g.get("module")})
    primary_module = module_names[0] if module_names else args.ip
    raw_texts = [f.summary for f in findings] + [p.__dict__.get("action", "") for p in plan]
    candidate_signals = _extract_signals(raw_texts)[:30]  # cap to 30 to avoid over-querying
    graph_ctx_text = _query_neo4j_context(primary_module, candidate_signals) if candidate_signals else ""

    model_cfg = load_model_config(args.model_config)
    llm_summary = None
    if model_cfg:
        prompt = "Summarize the following findings and action plan:\n"
        if graph_ctx_text:
            prompt = (
                "## Graph Context (from Neo4j)\n"
                f"{graph_ctx_text}\n\n"
                + prompt
            )
        prompt += json.dumps({
            "findings": [f.__dict__ for f in findings],
            "plan": [p.__dict__ for p in plan],
        }, indent=2)
        llm_summary = call_llm(prompt, model_cfg)

    verification = None
    if args.generate_rtl:
        if not model_cfg:
            raise ValueError("Model config is required for RTL generation")
        generate_rtl(
            model_cfg,
            args.origin_rtl,
            args.uarch_origin,
            args.uarch_new,
            args.algo_origin,
            args.algo_new,
            args.output_rtl,
        )
        causal_graph_path = build_dir / "causal_graph.json"
        verification = run_checks(args.output_rtl, causal_graph_path=causal_graph_path)
        status = verification["status"]
        print(f"[flow] generated RTL -> {args.output_rtl} ({status})")
        if status == "fail":
            failed = [
                f"  [{name}] {res.get('detail', '')} {res.get('missing_edges', '')}"
                for name, res in verification["results"].items()
                if res.get("status") == "fail"
            ]
            print("[flow] verification failures:")
            for line in failed:
                print(line)

    write_report(Path(args.out), findings, plan, llm_summary)
    Path("outputs/bundle.json").write_text(json.dumps({
        "findings": [f.__dict__ for f in findings],
        "plan": [p.__dict__ for p in plan],
        "graph_notes": graph_notes,
        "llm_summary": llm_summary,
        "verification": verification,
        "rtl_output": str(args.output_rtl) if args.generate_rtl else None,
    }, indent=2))
    print(f"[flow] report saved to {args.out}")


if __name__ == "__main__":
    main()
