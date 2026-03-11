#!/usr/bin/env python3
"""Generate a simple unified diff between two pseudo files."""
from __future__ import annotations

import argparse
import json
import difflib
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("old", type=Path)
    parser.add_argument("new", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    old_lines = args.old.read_text().splitlines()
    new_lines = args.new.read_text().splitlines()
    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm=""))

    payload = {
        "old": str(args.old),
        "new": str(args.new),
        "diff": diff,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2))
    print(f"[diff_pseudo] diff size {len(diff)} lines -> {args.output}")


if __name__ == "__main__":
    main()
