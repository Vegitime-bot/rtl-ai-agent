#!/usr/bin/env python3
"""Split a micro-architecture markdown doc into section chunks."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

SECTION_RE = re.compile(r"^##\s+(.*)$", re.M)


def chunk(text: str) -> list[dict]:
    sections = []
    matches = list(SECTION_RE.finditer(text))
    if not matches:
        return [{"section": "root", "body": text.strip()}]

    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        sections.append({
            "section": match.group(1).strip(),
            "body": body,
        })
    return sections


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    sections = chunk(args.input.read_text())
    payload = {
        "doc": str(args.input),
        "sections": sections,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2))
    print(f"[chunk_ma] sections: {len(sections)} -> {args.output}")


if __name__ == "__main__":
    main()
