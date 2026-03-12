#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path

import requests
import yaml

from agents.plan_agent import build_plan
from agents.report_agent import write_report
from agents.spec_agent import analyze


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


def summarize_graphs(data: dict) -> list[str]:
    notes: list[str] = []
    for graph in data.get("graphs", []):
        for edge in graph.get("edges", [])[:5]:
            notes.append(f"{graph['module']}: {edge['from']} -> {edge['to']} ({edge['kind']})")
    return notes


def load_model_config(path: Path | None) -> dict | None:
    if not path:
        return None
    data = yaml.safe_load(path.read_text())
    api_key = data.get("api_key") or os.getenv("MODEL_API_KEY", "")
    data["api_key"] = api_key
    return data


def call_llm(prompt: str, cfg: dict) -> str:
    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": "You are an RTL design assistant."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    try:
        resp = requests.post(cfg["endpoint"].rstrip("/") + "/chat/completions", json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as exc:  # noqa: BLE001
        return f"LLM call failed: {exc}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", default="demo")
    parser.add_argument("--db", default="build/rag.db")
    parser.add_argument("--out", default="outputs/analysis.md")
    parser.add_argument("--model-config", type=Path)
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

    model_cfg = load_model_config(args.model_config)
    llm_summary = None
    if model_cfg:
        prompt = "Summarize the following findings and action plan:\n"
        prompt += json.dumps({
            "findings": [f.__dict__ for f in findings],
            "plan": [p.__dict__ for p in plan],
        }, indent=2)
        llm_summary = call_llm(prompt, model_cfg)

    write_report(Path(args.out), findings, plan, llm_summary)
    Path("outputs/bundle.json").write_text(json.dumps({
        "findings": [f.__dict__ for f in findings],
        "plan": [p.__dict__ for p in plan],
        "graph_notes": graph_notes,
        "llm_summary": llm_summary,
    }, indent=2))
    print(f"[flow] report saved to {args.out}")


if __name__ == "__main__":
    main()
