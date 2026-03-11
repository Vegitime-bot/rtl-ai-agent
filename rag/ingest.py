#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  ref  TEXT NOT NULL,
  content TEXT NOT NULL,
  metadata TEXT
);
DELETE FROM chunks;
"""


def load_json(path: Path) -> list[tuple[str, str, str, str]]:
    data = json.loads(path.read_text())
    rows: list[tuple[str, str, str, str]] = []
    if "modules" in data:
        for module in data["modules"]:
            rows.append(("rtl", module["module"], json.dumps(module), json.dumps(module)))
    elif "diff" in data:
        rows.append(("pseudo_diff", data["new"], "\n".join(data["diff"]), json.dumps(data)))
    elif "sections" in data:
        for section in data["sections"]:
            rows.append(("ma", section["section"], section["body"], json.dumps(section)))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("inputs", nargs="+", type=Path)
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    with conn:
        conn.executescript(SCHEMA)
        for path in args.inputs:
            for row in load_json(path):
                conn.execute("INSERT INTO chunks(kind, ref, content, metadata) VALUES (?,?,?,?)", row)
    print(f"[rag.ingest] inserted data into {args.db}")


if __name__ == "__main__":
    main()
