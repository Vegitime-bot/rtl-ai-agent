#!/usr/bin/env python3
"""Ingest RTL causal graphs into a Neo4j database."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

from neo4j import GraphDatabase, Session


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load build/causal_graph.json into Neo4j")
    parser.add_argument("--graph-json", type=Path, default=Path("build/causal_graph.json"), help="Path to causal graph JSON")
    parser.add_argument("--rtl-json", type=Path, default=Path("build/rtl_ast.json"), help="Path to rtl_ast JSON (for metadata)")
    parser.add_argument("--uri", default="bolt://localhost:7687", help="Neo4j Bolt URI")
    parser.add_argument("--user", default="neo4j", help="Neo4j username")
    parser.add_argument("--password", required=True, help="Neo4j password")
    parser.add_argument("--module", help="Only ingest the specified module")
    parser.add_argument("--clear", action="store_true", help="Remove existing Signal nodes for the target module(s) before ingest")
    return parser.parse_args()


def load_graphs(path: Path) -> List[dict]:
    data = json.loads(path.read_text())
    return data.get("graphs", [])


def load_modules(path: Path) -> Dict[str, dict]:
    data = json.loads(path.read_text())
    return {module["module"]: module for module in data.get("modules", [])}


def build_signal_index(module: dict) -> Dict[str, dict]:
    meta: Dict[str, dict] = {}
    for signal in module.get("signals", []):
        meta[signal["name"]] = {
            "width": signal.get("width"),
        }
    for port in module.get("ports", []):
        name = port.get("net") or port.get("name")
        if not name:
            continue
        entry = meta.setdefault(name, {"width": None})
        entry["port_direction"] = port.get("direction")
    return meta


def clear_module(session: Session, module: str | None) -> None:
    if module:
        session.run("MATCH (s:Signal {module:$module}) DETACH DELETE s", module=module)
    else:
        session.run("MATCH (s:Signal) DETACH DELETE s")


def ingest_module(session: Session, module: str, graph: dict, signal_meta: Dict[str, dict]) -> dict:
    created = {"nodes": 0, "edges": 0}
    for name, kind in graph.get("node_kinds", {}).items():
        meta = signal_meta.get(name, {})
        session.run(
            """
            MERGE (s:Signal {module:$module, name:$name})
            SET s.kind = $kind,
                s.width = COALESCE($width, s.width),
                s.port_direction = COALESCE($port_direction, s.port_direction)
            """,
            module=module,
            name=name,
            kind=kind,
            width=meta.get("width"),
            port_direction=meta.get("port_direction"),
        )
        created["nodes"] += 1
    for edge in graph.get("edges", []):
        session.run(
            """
            MATCH (src:Signal {module:$module, name:$src})
            MATCH (dst:Signal {module:$module, name:$dst})
            MERGE (src)-[r:DRIVES {kind:$kind}]->(dst)
            """,
            module=module,
            src=edge["from"],
            dst=edge["to"],
            kind=edge.get("kind"),
        )
        created["edges"] += 1
    return created


def main() -> None:
    args = parse_args()
    graphs = load_graphs(args.graph_json)
    modules = load_modules(args.rtl_json)

    if args.module:
        graphs = [g for g in graphs if g.get("module") == args.module]
        if args.module not in modules:
            raise SystemExit(f"Module {args.module} not found in {args.rtl_json}")

    driver = GraphDatabase.driver(args.uri, auth=(args.user, args.password))
    try:
        with driver.session(database=None) as session:
            if args.clear:
                target = args.module if args.module else None
                clear_module(session, target)
            total_nodes = 0
            total_edges = 0
            for graph in graphs:
                module_name = graph.get("module")
                module_meta = build_signal_index(modules.get(module_name, {}))
                counts = ingest_module(session, module_name, graph, module_meta)
                total_nodes += counts["nodes"]
                total_edges += counts["edges"]
            print(f"[neo4j_ingest] modules: {len(graphs)} nodes={total_nodes} edges={total_edges}")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
