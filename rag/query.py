#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def search(conn: sqlite3.Connection, keyword: str, limit: int = 5) -> list[dict]:
    cur = conn.execute(
        "SELECT kind, ref, content FROM chunks WHERE content LIKE ? LIMIT ?",
        (f"%{keyword}%", limit),
    )
    return [dict(zip(["kind", "ref", "content"], row)) for row in cur.fetchall()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("keyword")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    hits = search(conn, args.keyword)
    print(json.dumps(hits, indent=2))


if __name__ == "__main__":
    main()
