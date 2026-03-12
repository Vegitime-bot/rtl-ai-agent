#!/usr/bin/env python3
"""Build a simple causal graph based on assignments."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("rtl_json", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    rtl = json.loads(args.rtl_json.read_text())
    graphs = []
    for module in rtl.get("modules", []):
        edges = []
        fan_in = defaultdict(int)
        for assign in module.get("assignments", []):
            lhs = assign["lhs"]
            for token in assign.get("rhs", []):
                edges.append({"from": token, "to": lhs, "kind": assign.get("kind", "assign")})
                fan_in[lhs] += 1
        graphs.append({
            "module": module["module"],
            "edges": edges,
            "fan_in": fan_in,
        })
    serializable = {
        "graphs": [
            {
                "module": g["module"],
                "edges": g["edges"],
                "fan_in": dict(g["fan_in"]),
            }
            for g in graphs
        ]
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(serializable, indent=2))
    print(f"[build_graph] modules: {len(graphs)} -> {args.output}")


if __name__ == "__main__":
    main()
