#!/usr/bin/env python3
"""Reusable Neo4j query helpers for RTL causal graph lookups."""
from __future__ import annotations

import argparse
import os
import warnings
from pathlib import Path
from typing import Dict, List

import yaml


def _load_connection(config_path: Path | None = None) -> dict:
    """Load Neo4j connection params from config/neo4j.yaml + NEO4J_PASSWORD env."""
    cfg: dict = {}
    resolved = config_path or Path("config/neo4j.yaml")
    if resolved.exists():
        cfg = yaml.safe_load(resolved.read_text()) or {}
    uri = cfg.get("uri", "bolt://127.0.0.1:7687")
    user = cfg.get("user", "neo4j")
    password = cfg.get("password")
    if not password:
        env_key = cfg.get("password_env", "NEO4J_PASSWORD")
        password = os.getenv(env_key, "")
    return {"uri": uri, "user": user, "password": password}


def _make_driver(config_path: Path | None = None):
    """Return a Neo4j driver, or raise if neo4j package is missing."""
    from neo4j import GraphDatabase  # type: ignore
    conn = _load_connection(config_path)
    return GraphDatabase.driver(conn["uri"], auth=(conn["user"], conn["password"]))


def get_signal_drivers(module: str, signal: str, config_path: Path | None = None) -> List[str]:
    """Return list of signal names that DRIVE the given signal (incoming DRIVES edges)."""
    driver = _make_driver(config_path)
    try:
        with driver.session(database=None) as session:
            result = session.run(
                """
                MATCH (src:Signal {module: $module})-[:DRIVES]->(dst:Signal {module: $module, name: $signal})
                RETURN src.name AS name
                """,
                module=module,
                signal=signal,
            )
            return [row["name"] for row in result]
    finally:
        driver.close()


def get_signal_dependents(module: str, signal: str, config_path: Path | None = None) -> List[str]:
    """Return list of signal names DRIVEN BY the given signal (outgoing DRIVES edges)."""
    driver = _make_driver(config_path)
    try:
        with driver.session(database=None) as session:
            result = session.run(
                """
                MATCH (src:Signal {module: $module, name: $signal})-[:DRIVES]->(dst:Signal {module: $module})
                RETURN dst.name AS name
                """,
                module=module,
                signal=signal,
            )
            return [row["name"] for row in result]
    finally:
        driver.close()


def get_causal_context(module: str, signals: List[str], config_path: Path | None = None) -> Dict[str, Dict[str, List[str]]]:
    """
    For each signal in *signals*, return 1-hop neighbors from Neo4j.

    Returns:
        {
          "signal_name": {
            "drivers": [...],
            "dependents": [...]
          },
          ...
        }
    """
    if not signals:
        return {}

    driver = _make_driver(config_path)
    context: Dict[str, Dict[str, List[str]]] = {}
    try:
        with driver.session(database=None) as session:
            for signal in signals:
                drivers_result = session.run(
                    """
                    MATCH (src:Signal {module: $module})-[:DRIVES]->(dst:Signal {module: $module, name: $signal})
                    RETURN src.name AS name
                    """,
                    module=module,
                    signal=signal,
                )
                drivers = [row["name"] for row in drivers_result]

                dependents_result = session.run(
                    """
                    MATCH (src:Signal {module: $module, name: $signal})-[:DRIVES]->(dst:Signal {module: $module})
                    RETURN dst.name AS name
                    """,
                    module=module,
                    signal=signal,
                )
                dependents = [row["name"] for row in dependents_result]

                if drivers or dependents:
                    context[signal] = {"drivers": drivers, "dependents": dependents}
    finally:
        driver.close()
    return context


def get_causal_context_nhop(
    module: str,
    signals: List[str],
    n_hops: int = 1,
    config_path: Path | None = None,
) -> Dict[str, Dict[str, List[str]]]:
    """
    n-hop 이웃을 Neo4j에서 조회한다.

    n_hops=1 : 직접 driver/dependent만 (기존 get_causal_context와 동일)
    n_hops=2 : 1-hop 이웃의 이웃까지 포함

    반환:
        {
          "signal_name": {
            "drivers": [...],       # 이 신호를 drive하는 신호들 (n-hop 내)
            "dependents": [...],    # 이 신호가 drive하는 신호들 (n-hop 내)
            "hop": 1 | 2,           # 최초 요청 신호로부터의 거리
          },
          ...
        }
    """
    if not signals or n_hops < 1:
        return {}

    driver = _make_driver(config_path)
    context: Dict[str, Dict[str, List[str]]] = {}

    try:
        with driver.session(database=None) as session:
            # Neo4j Cypher에서 가변 경로 길이는 파라미터 불가 → 숫자 직접 포맷팅
            hops_str = str(n_hops)
            for signal in signals:
                # n-hop upstream (drivers)
                upstream = session.run(
                    f"""
                    MATCH path = (src:Signal {{module: $module}})
                          -[:DRIVES*1..{hops_str}]->
                          (dst:Signal {{module: $module, name: $signal}})
                    WITH src, length(path) AS hop
                    RETURN src.name AS name, min(hop) AS min_hop
                    ORDER BY min_hop, src.name
                    """,
                    module=module,
                    signal=signal,
                )
                drivers_with_hop = [(row["name"], row["min_hop"]) for row in upstream]

                # n-hop downstream (dependents)
                downstream = session.run(
                    f"""
                    MATCH path = (src:Signal {{module: $module, name: $signal}})
                          -[:DRIVES*1..{hops_str}]->
                          (dst:Signal {{module: $module}})
                    WITH dst, length(path) AS hop
                    RETURN dst.name AS name, min(hop) AS min_hop
                    ORDER BY min_hop, dst.name
                    """,
                    module=module,
                    signal=signal,
                )
                dependents_with_hop = [(row["name"], row["min_hop"]) for row in downstream]

                if drivers_with_hop or dependents_with_hop:
                    context[signal] = {
                        "drivers":    [n for n, _ in drivers_with_hop],
                        "dependents": [n for n, _ in dependents_with_hop],
                        "driver_hops":    {n: h for n, h in drivers_with_hop},
                        "dependent_hops": {n: h for n, h in dependents_with_hop},
                    }
    finally:
        driver.close()

    return context


def format_graph_context(context: Dict[str, Dict[str, List[str]]]) -> str:
    """
    causal context dict를 LLM 프롬프트 주입용 텍스트 블록으로 포맷.
    hop 정보가 있으면 (hop=N) 표기.
    """
    if not context:
        return "(no graph context available)"
    lines: List[str] = []
    for signal, neighbors in sorted(context.items()):
        drivers    = neighbors.get("drivers", [])
        dependents = neighbors.get("dependents", [])
        d_hops     = neighbors.get("driver_hops", {})
        dep_hops   = neighbors.get("dependent_hops", {})

        if drivers:
            parts = []
            for d in sorted(drivers):
                hop = d_hops.get(d)
                parts.append(f"{d}(hop={hop})" if hop and hop > 1 else d)
            lines.append(f"  {signal} <- driven by: {', '.join(parts)}")
        if dependents:
            parts = []
            for d in sorted(dependents):
                hop = dep_hops.get(d)
                parts.append(f"{d}(hop={hop})" if hop and hop > 1 else d)
            lines.append(f"  {signal} -> drives: {', '.join(parts)}")
    return "\n".join(lines) if lines else "(no causal edges found for requested signals)"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Query Neo4j causal graph for a signal")
    parser.add_argument("--module", required=True, help="RTL module name")
    parser.add_argument("--signal", required=True, help="Signal name to inspect")
    parser.add_argument("--config", type=Path, help="Path to neo4j.yaml (default: config/neo4j.yaml)")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    try:
        ctx = get_causal_context(args.module, [args.signal], config_path=args.config)
        print(format_graph_context(ctx))
    except Exception as exc:  # noqa: BLE001
        warnings.warn(f"[neo4j_query] failed: {exc}", stacklevel=1)
