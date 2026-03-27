#!/usr/bin/env python3
"""Build a causal graph from structured RTL assignments."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List


def load_modules(path: Path) -> List[dict]:
    data = json.loads(path.read_text())
    return data.get("modules", [])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("rtl_json", type=Path, help="Structured RTL JSON (from uhdm_extract)")
    parser.add_argument("output", type=Path, help="Graph JSON output")
    args = parser.parse_args()

    modules = load_modules(args.rtl_json)
    graphs: List[Dict] = []
    for module in modules:
        edges: List[Dict] = []
        node_kinds: Dict[str, str] = {}
        for signal in module.get("signals", []):
            node_kinds[signal["name"]] = "signal"
        for port in module.get("ports", []):
            target = port.get("net") or port.get("name")
            if not target:
                continue
            if port.get("direction") == "input":
                node_kinds[target] = "input"
            elif port.get("direction") == "output":
                node_kinds[target] = "output"

        def add_edges(assign_list: List[dict], kind: str) -> None:
            for assign in assign_list:
                lhs = assign.get("lhs")
                if not lhs:
                    continue
                sources = assign.get("rhs_signals") or assign.get("rhs") or []
                for source in sources:
                    edges.append({"from": source, "to": lhs, "kind": kind})

        add_edges(module.get("continuous_assignments", []), "continuous")
        add_edges(module.get("procedural_assignments", []), "procedural")
        if module.get("assignments"):
            add_edges(module.get("assignments"), "inferred")

        # function 내부 assignments → causal edge (kind: "function")
        for func in module.get("functions", []):
            fname = func.get("name", "")
            for assign in func.get("assignments", []):
                lhs = assign.get("lhs")
                if not lhs:
                    continue
                sources = assign.get("rhs") or []
                for source in sources:
                    edges.append({
                        "from": source,
                        "to": lhs,
                        "kind": "function",
                        "function": fname,
                    })
            # function 자체를 호출하는 신호 노드로 등록
            node_kinds[fname] = "function"

        graphs.append({
            "module": module.get("module"),
            "edges": edges,
            "node_kinds": node_kinds,
        })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"graphs": graphs}, indent=2))
    print(f"[build_graph] modules: {len(graphs)} -> {args.output}")


if __name__ == "__main__":
    main()
