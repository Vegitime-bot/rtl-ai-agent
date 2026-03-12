#!/usr/bin/env python3
"""Very small RTL parser that extracts module names and ports."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

MODULE_RE = re.compile(r"module\s+(?P<name>\w+)\s*\((?P<ports>.*?)\);(?P<body>.*?)endmodule", re.S)
PORT_RE = re.compile(r"(input|output|inout)\s+(?:logic|wire|reg)?\s*(\[[^\]]+\])?\s*(\w+)")
DECL_RE = re.compile(r"(logic|wire|reg)\s*(\[[^\]]+\])?\s*(\w+)")
ASSIGN_RE = re.compile(r"(assign\s+)?(\w+)\s*(<=|=)\s*([^;]+);")
IDENT_RE = re.compile(r"[A-Za-z_][\w$]*")
RESERVED = {"if", "else", "begin", "end", "posedge", "negedge", "module", "assign", "always"}


def extract_tokens(expr: str) -> list[str]:
    tokens = []
    for tok in IDENT_RE.findall(expr):
        if tok not in RESERVED:
            tokens.append(tok)
    return tokens


def parse_file(path: Path) -> list[dict]:
    text = path.read_text()
    modules = []
    for match in MODULE_RE.finditer(text):
        ports_text = match.group("ports")
        body = match.group("body")
        ports = []
        for kind, width, name in PORT_RE.findall(ports_text):
            ports.append({
                "direction": kind,
                "name": name,
                "width": width or "1"
            })
        signals = []
        for dtype, width, name in DECL_RE.findall(body):
            signals.append({
                "name": name,
                "width": width or "1",
                "type": dtype,
            })
        assignments = []
        for match_assign in ASSIGN_RE.finditer(body):
            is_continuous = bool(match_assign.group(1))
            lhs = match_assign.group(2)
            rhs = match_assign.group(4)
            assignments.append({
                "lhs": lhs,
                "rhs": extract_tokens(rhs),
                "kind": "assign" if is_continuous else "always",
            })
        modules.append({
            "module": match.group("name"),
            "file": str(path),
            "ports": ports,
            "signals": signals,
            "assignments": assignments,
        })
    return modules


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("rtl_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    data = []
    files = list(args.rtl_dir.glob("*.sv")) + list(args.rtl_dir.glob("*.v"))
    for path in sorted(files):
        data.extend(parse_file(path))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"modules": data}, indent=2))
    print(f"[parse_rtl] Wrote {len(data)} modules -> {args.output}")


if __name__ == "__main__":
    main()
