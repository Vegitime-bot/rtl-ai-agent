#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", default="demo")
    parser.add_argument("--db", default="build/rag.db")
    parser.add_argument("--out", default="outputs/analysis.md")
    args = parser.parse_args()

    build_dir = Path("build")
    rtl_data = load_json(build_dir / "rtl_ast.json")
    pseudo_diff = load_json(build_dir / "pseudo_diff.json")["diff"]
    conn = sqlite3.connect(args.db)
    ma_chunks = [c for c in query_chunks(conn, args.ip) if c["kind"] == "ma"]

    findings = analyze(ma_chunks, "\n".join(pseudo_diff))
    plan = build_plan(rtl_data.get("modules", []), [f.summary for f in findings])

    write_report(Path(args.out), findings, plan)
    Path("outputs/bundle.json").write_text(json.dumps({
        "findings": [f.__dict__ for f in findings],
        "plan": [p.__dict__ for p in plan],
    }, indent=2))
    print(f"[flow] report saved to {args.out}")


if __name__ == "__main__":
    main()
