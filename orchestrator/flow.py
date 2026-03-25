#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import warnings
from pathlib import Path

from agents.plan_agent import build_plan
from agents.report_agent import write_report
from agents.spec_agent import analyze
from codegen import generate_rtl, generate_rtl_with_retry
from llm_utils import call_llm, load_model_config, safe_input_token_budget
# run_checks is called inside codegen.generate_rtl_with_retry


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text())


def query_spec_context(
    query: str,
    index_dir: Path,
    model_name_or_path: str = "BAAI/bge-m3",
    top_k: int = 5,
    kind_filter: list[str] | None = None,
) -> list[dict]:
    """
    FAISS 인덱스에서 시맨틱 검색.
    인덱스가 없으면 graceful skip (빈 리스트 반환).
    """
    try:
        rag_dir = Path(__file__).parent.parent / "rag"
        if str(rag_dir) not in sys.path:
            sys.path.insert(0, str(rag_dir))
        from query_faiss import search  # type: ignore
        return search(
            query,
            index_dir=index_dir,
            top_k=top_k,
            model_name_or_path=model_name_or_path,
            kind_filter=kind_filter,
        )
    except FileNotFoundError:
        warnings.warn(
            f"[flow] FAISS index not found at {index_dir}. "
            "Run rag/ingest_faiss.py to build it. Skipping semantic search.",
            stacklevel=2,
        )
        return []
    except Exception as exc:  # noqa: BLE001
        warnings.warn(f"[flow] FAISS search failed: {exc}", stacklevel=2)
        return []


_SIGNAL_RE = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]{1,63})\b")
_STOP_WORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "in", "on", "at", "to",
    "of", "and", "or", "not", "for", "with", "from", "that", "this",
    "module", "signal", "logic", "reg", "wire", "input", "output",
    "always", "assign", "begin", "end", "if", "else", "case",
})


def _extract_signals(texts: list[str]) -> list[str]:
    """Heuristically extract Verilog-style identifiers from free-text strings."""
    seen: dict[str, int] = {}
    for text in texts:
        for m in _SIGNAL_RE.finditer(text):
            tok = m.group(1)
            if tok.lower() not in _STOP_WORDS and not tok[0].isupper():
                seen[tok] = seen.get(tok, 0) + 1
    # Return identifiers that appear at least once, sorted by frequency desc
    return [k for k, _ in sorted(seen.items(), key=lambda x: -x[1])]


def _query_neo4j_context(
    module: str,
    signals: list[str],
    n_hops: int = 1,
    output_ports: list[str] | None = None,
) -> str:
    """
    Neo4j에서 causal context를 조회.
    - output_ports 신호: n_hops+1 hop (더 넓은 컨텍스트)
    - 일반 신호: n_hops hop
    Neo4j 미연결 시 graceful skip.
    """
    try:
        scripts_dir = Path(__file__).parent.parent / "scripts"
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        from neo4j_query import get_causal_context_nhop, format_graph_context  # type: ignore

        output_ports = output_ports or []
        output_set = set(output_ports)

        regular = [s for s in signals if s not in output_set]
        critical = [s for s in signals if s in output_set]

        ctx: dict = {}

        if regular:
            ctx.update(get_causal_context_nhop(module, regular, n_hops=n_hops))

        if critical:
            # 출력 포트는 n_hops+1 hop — 상위 드라이버 체인까지 파악
            ctx.update(get_causal_context_nhop(module, critical, n_hops=n_hops + 1))

        return format_graph_context(ctx)
    except Exception as exc:  # noqa: BLE001
        warnings.warn(f"[flow] Neo4j not reachable, skipping graph context: {exc}", stacklevel=2)
        return ""


def summarize_graphs(data: dict) -> list[str]:
    notes: list[str] = []
    for graph in data.get("graphs", []):
        for edge in graph.get("edges", [])[:5]:
            notes.append(f"{graph['module']}: {edge['from']} -> {edge['to']} ({edge['kind']})")
    return notes




def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", default="demo")
    parser.add_argument("--db", default="build/rag.db",
                        help="[deprecated] SQLite DB path (ignored, kept for backward compat)")
    parser.add_argument("--faiss-index", type=Path, default=Path("build/faiss_index"),
                        help="FAISS index directory (default: build/faiss_index)")
    parser.add_argument("--embed-model", type=str, default=None,
                        help="BGE-M3 모델 경로 (생략 시 models/bge-m3/ 자동 사용)")
    parser.add_argument("--out", default="outputs/analysis.md")
    parser.add_argument("--model-config", type=Path)
    parser.add_argument("--origin-rtl-dir", type=Path, default=Path("inputs/rtl"),
                        help="*.v / *.sv RTL 디렉토리 (기본: inputs/rtl/)")
    parser.add_argument("--uarch-origin", type=Path, default=Path("inputs/uArch_origin.txt"),
                        help="uArch origin 문서 (없으면 자동 스킵)")
    parser.add_argument("--uarch-new", type=Path, default=Path("inputs/uArch_new.txt"),
                        help="uArch new 문서 (없으면 자동 스킵)")
    parser.add_argument("--algo-origin-dir", type=Path,
                        default=Path("inputs/algorithm/origin"),
                        help="origin 알고리즘 디렉토리 (기본: inputs/algorithm/origin/)")
    parser.add_argument("--algo-new-dir", type=Path,
                        default=Path("inputs/algorithm/new"),
                        help="new 알고리즘 디렉토리 (기본: inputs/algorithm/new/)")
    parser.add_argument("--generate-rtl", action="store_true")
    parser.add_argument("--output-rtl", type=Path, default=Path("outputs/new.v"))
    parser.add_argument("--max-retries", type=int, default=2,
                        help="Max re-generation attempts on verification failure (default: 2)")
    parser.add_argument("--token-budget", type=int, default=6000,
                        help="RTL context token budget for chunked mode (default: 6000)")
    parser.add_argument("--graph-hops", type=int, default=1,
                        help="Neo4j causal graph hop depth for regular signals (default: 1). "
                             "Output ports always use graph-hops+1.")
    parser.add_argument("--output-max-tokens", type=int, default=8192,
                        help="Max output tokens for RTL generation LLM calls (default: 8192)")
    args = parser.parse_args()

    origin_rtl_dir = args.origin_rtl_dir

    algo_origin_path = args.algo_origin_dir
    algo_new_path    = args.algo_new_dir

    print(f"[flow] algo origin: {algo_origin_path}")
    print(f"[flow] algo new   : {algo_new_path}")
    print(f"[flow] graph hops: {args.graph_hops} (output ports: {args.graph_hops + 1})")

    build_dir = Path("build")
    rtl_data = load_json(build_dir / "rtl_ast.json")
    pseudo_diff = load_json(build_dir / "pseudo_diff.json")["diff"]
    graph_path = build_dir / "causal_graph.json"
    graph_data = load_json(graph_path) if graph_path.exists() else {"graphs": []}

    # 스펙 관련 청크를 FAISS 시맨틱 검색으로 조회
    spec_query = f"RTL module specification changes {args.ip}"
    spec_chunks = query_spec_context(
        spec_query,
        index_dir=args.faiss_index,
        model_name_or_path=args.embed_model,
        top_k=8,
        kind_filter=["uarch", "algorithm"],
    )
    # spec_agent가 기대하는 형식으로 변환 (content 키)
    ma_chunks = [
        {"kind": c.get("kind", "ma"), "ref": c.get("ref", ""), "content": c.get("text", "")}
        for c in spec_chunks
    ]

    model_cfg = load_model_config(args.model_config)
    findings = analyze(ma_chunks, "\n".join(pseudo_diff), model_cfg=model_cfg)
    graph_notes = summarize_graphs(graph_data)
    plan = build_plan(rtl_data.get("modules", []), [f.summary for f in findings], graph_notes, model_cfg=model_cfg)

    # --- Neo4j graph context injection ---
    module_names = list({g.get("module") for g in graph_data.get("graphs", []) if g.get("module")})
    primary_module = module_names[0] if module_names else args.ip
    raw_texts = [f.summary for f in findings] + [p.__dict__.get("action", "") for p in plan]
    candidate_signals = _extract_signals(raw_texts)[:30]  # cap to 30 to avoid over-querying

    # 출력 포트 목록 추출 (2-hop 대상)
    output_ports: list[str] = []
    for mod in rtl_data.get("modules", []):
        output_ports += [p["name"] for p in mod.get("ports", []) if p.get("direction") == "output"]

    graph_ctx_text = (
        _query_neo4j_context(
            primary_module,
            candidate_signals,
            n_hops=args.graph_hops,
            output_ports=output_ports,
        )
        if candidate_signals else ""
    )
    llm_summary = None
    if model_cfg:
        prompt = "Summarize the following findings and action plan:\n"
        if graph_ctx_text:
            prompt = (
                "## Graph Context (from Neo4j)\n"
                f"{graph_ctx_text}\n\n"
                + prompt
            )
        prompt += json.dumps({
            "findings": [f.__dict__ for f in findings],
            "plan": [p.__dict__ for p in plan],
        }, indent=2)
        llm_summary = call_llm(prompt, model_cfg, max_tokens=1024)

    verification = None
    if args.generate_rtl:
        if not model_cfg:
            raise ValueError("Model config is required for RTL generation")
        causal_graph_path = build_dir / "causal_graph.json"
        rtl_chunks_path   = build_dir / "rtl_chunks.json"
        pseudo_diff_path  = build_dir / "pseudo_diff.json"
        uarch_origin = args.uarch_origin if args.uarch_origin.exists() else None
        uarch_new    = args.uarch_new    if args.uarch_new.exists()    else None
        if uarch_origin is None:
            warnings.warn(f"[flow] uArch origin 없음, 스킵: {args.uarch_origin}", stacklevel=1)
        if uarch_new is None:
            warnings.warn(f"[flow] uArch new 없음, 스킵: {args.uarch_new}", stacklevel=1)

        # token_budget: CLI 지정 없으면 context_window 기반 자동 계산
        effective_token_budget = (
            args.token_budget
            if args.token_budget != 6000  # 기본값이면 자동 계산
            else safe_input_token_budget(model_cfg)
        )
        print(f"[flow] input token budget: {effective_token_budget} tokens")

        _, verification = generate_rtl_with_retry(
            model_cfg,
            origin_rtl_dir,
            uarch_origin,
            uarch_new,
            algo_origin_path,
            algo_new_path,
            args.output_rtl,
            causal_graph_path=causal_graph_path,
            max_retries=args.max_retries,
            rtl_chunks_path=rtl_chunks_path,
            pseudo_diff_path=pseudo_diff_path,
            token_budget=effective_token_budget,
            graph_ctx_text=graph_ctx_text,
            output_max_tokens=args.output_max_tokens,
        )
        status = verification["status"]
        print(f"[flow] final RTL -> {args.output_rtl} ({status})")

    write_report(Path(args.out), findings, plan, llm_summary)
    Path("outputs/bundle.json").write_text(json.dumps({
        "findings": [f.__dict__ for f in findings],
        "plan": [p.__dict__ for p in plan],
        "graph_notes": graph_notes,
        "llm_summary": llm_summary,
        "verification": verification,
        "rtl_output": str(args.output_rtl) if args.generate_rtl else None,
    }, indent=2))
    print(f"[flow] report saved to {args.out}")


if __name__ == "__main__":
    main()
