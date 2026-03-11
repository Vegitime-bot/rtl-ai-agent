#!/usr/bin/env python3
"""Very small RTL parser that extracts module names and ports."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

MODULE_RE = re.compile(r"module\s+(?P<name>\w+)\s*\((?P<ports>.*?)\);", re.S)
PORT_RE = re.compile(r"(input|output|inout)\s+(?:logic|wire|reg)?\s*(\[[^\]]+\])?\s*(\w+)")


def parse_file(path: Path) -> list[dict]:
    text = path.read_text()
    modules = []
    for match in MODULE_RE.finditer(text):
        ports_text = match.group("ports")
        ports = []
        for kind, width, name in PORT_RE.findall(ports_text):
            ports.append({
                "direction": kind,
                "name": name,
                "width": width or "1"
            })
        modules.append({
            "module": match.group("name"),
            "file": str(path),
            "ports": ports
        })
    return modules


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("rtl_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    data = []
    for path in sorted(args.rtl_dir.glob("*.sv")):
        data.extend(parse_file(path))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"modules": data}, indent=2))
    print(f"[parse_rtl] Wrote {len(data)} modules -> {args.output}")


if __name__ == "__main__":
    main()
