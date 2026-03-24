"""
orchestrator/context_selector.py
──────────────────────────────────
변경 영향 범위(diff scope)를 기반으로 RTL 청크를 선택하고,
LLM 컨텍스트 윈도우 예산에 맞게 조합한다.

핵심 함수:
  select_chunks(chunks, diff_signals, causal_edges, token_budget)
      → ChunkSelection

  build_chunked_prompt(selection, uarch_origin, uarch_new, algo_origin, algo_new)
      → str  (LLM에 넣을 프롬프트)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# ────────────────────────────────────────────
# 타입
# ────────────────────────────────────────────

@dataclass
class ChunkSelection:
    must_include: list[dict]    # header + footer + 변경 영향 청크
    context_include: list[dict] # 인접 청크 (예산 남으면 포함)
    omitted: list[dict]         # 생략된 청크
    estimated_tokens: int
    omitted_summary: str        # 생략된 청크 요약 (LLM에 텍스트로 전달)


# ────────────────────────────────────────────
# 헬퍼
# ────────────────────────────────────────────

def _approx_tokens(text: str) -> int:
    """대략적인 토큰 수 추정 (4자 = 1 token)."""
    return max(1, len(text) // 4)


def _signal_set(chunk: dict) -> set[str]:
    return set(chunk.get('signals', []))


def _lhs_set(chunk: dict) -> set[str]:
    return set(chunk.get('lhs', []))


# ────────────────────────────────────────────
# diff scope 신호 추출
# ────────────────────────────────────────────

VL_KEYWORDS = {
    'begin', 'end', 'if', 'else', 'case', 'casex', 'casez', 'endcase',
    'default', 'assign', 'always', 'posedge', 'negedge', 'or', 'and',
    'not', 'wire', 'reg', 'integer', 'parameter', 'localparam', 'module',
    'endmodule', 'input', 'output', 'inout', 'initial', 'for', 'while',
}

IDENT_RE = re.compile(r'\b([A-Za-z_]\w*)\b')


def extract_diff_signals(pseudo_diff: list[str]) -> set[str]:
    """
    pseudo_diff 텍스트에서 Verilog 식별자를 추출.
    (diff_pseudo.py 출력의 'diff' 리스트를 받음)
    """
    signals: set[str] = set()
    for line in pseudo_diff:
        for tok in IDENT_RE.findall(line):
            if tok not in VL_KEYWORDS and not tok[0].isupper():
                signals.add(tok)
    return signals


def expand_via_causal(signals: set[str], causal_edges: list[dict], hops: int = 1) -> set[str]:
    """
    causal_graph의 edges를 따라 신호 집합을 확장 (최대 hops hop).
    변경 신호가 영향을 주거나 받는 신호들을 포함.
    """
    expanded = set(signals)
    edge_pairs = [(e['from'], e['to']) for e in causal_edges]

    for _ in range(hops):
        new = set()
        for frm, to in edge_pairs:
            if frm in expanded:
                new.add(to)
            if to in expanded:
                new.add(frm)
        if new <= expanded:
            break
        expanded |= new

    return expanded


# ────────────────────────────────────────────
# 청크 선택
# ────────────────────────────────────────────

def select_chunks(
    chunks: list[dict],
    diff_signals: set[str],
    causal_edges: list[dict],
    token_budget: int = 6000,
    causal_hops: int = 1,
) -> ChunkSelection:
    """
    diff_signals + causal graph 기반으로 관련 청크를 선택.

    우선순위:
      P1 (must): header, footer — 항상 포함
      P2 (must): diff_signals와 직접 겹치는 always/assign 청크
      P3 (context): causal expand 신호와 겹치는 청크 (예산 내)
      P4 (omit): 나머지 → 요약 텍스트로 대체
    """
    expanded_signals = expand_via_causal(diff_signals, causal_edges, hops=causal_hops)

    must: list[dict] = []
    context: list[dict] = []
    omitted: list[dict] = []

    for chunk in chunks:
        kind = chunk['kind']
        sigs = _signal_set(chunk)
        lhs = _lhs_set(chunk)

        # P1: 항상 포함
        if kind in ('header', 'footer', 'localparam'):
            must.append(chunk)
            continue

        # P2: diff 신호와 직접 연관
        if sigs & diff_signals or lhs & diff_signals:
            must.append(chunk)
            continue

        # decl은 must에 포함 (짧고 필수 컨텍스트)
        if kind == 'decl':
            must.append(chunk)
            continue

        # P3: causal expand 신호와 연관
        if sigs & expanded_signals or lhs & expanded_signals:
            context.append(chunk)
        else:
            omitted.append(chunk)

    # 예산 계산
    must_tokens = sum(_approx_tokens(c['text']) for c in must)
    remaining = token_budget - must_tokens

    # P3 청크를 예산 내에서 추가
    context_included: list[dict] = []
    for chunk in context:
        t = _approx_tokens(chunk['text'])
        if remaining >= t:
            context_included.append(chunk)
            remaining -= t
        else:
            omitted.append(chunk)

    # 생략된 청크 요약 생성
    omit_summary_lines: list[str] = []
    if omitted:
        omit_summary_lines.append(
            f"[{len(omitted)} block(s) omitted for context budget — unchanged from origin.v]"
        )
        for c in omitted:
            lhs_str = ', '.join(c['lhs'][:4]) if c['lhs'] else '—'
            omit_summary_lines.append(
                f"  L{c['line_start']}-{c['line_end']} {c['kind']:8s}  drives: {lhs_str}"
            )

    total_tokens = sum(_approx_tokens(c['text']) for c in must + context_included)

    return ChunkSelection(
        must_include=must,
        context_include=context_included,
        omitted=omitted,
        estimated_tokens=total_tokens,
        omitted_summary='\n'.join(omit_summary_lines),
    )


# ────────────────────────────────────────────
# 프롬프트 조립
# ────────────────────────────────────────────

_ALGO_SUFFIXES = {".py", ".txt", ".sv", ".v"}


def _read(p: Path) -> str:
    """파일 또는 디렉토리를 읽어 문자열 반환."""
    if p.is_file():
        return p.read_text(encoding="utf-8") if p.exists() else f'[file not found: {p}]'
    if p.is_dir():
        files = sorted(f for f in p.iterdir() if f.is_file() and f.suffix in _ALGO_SUFFIXES)
        if not files:
            return f'[no algorithm files found in {p}]'
        parts: list[str] = []
        for f in files:
            parts.append(f"=== {f.name} ===")
            parts.append(f.read_text(encoding="utf-8"))
        return "\n".join(parts)
    return f'[path not found: {p}]'


def build_chunked_prompt(
    selection: ChunkSelection,
    uarch_origin: Path | None,
    uarch_new: Path | None,
    algo_origin: Path,
    algo_new: Path,
) -> str:
    """
    선택된 청크로 RTL 컨텍스트를 조립하고 LLM 프롬프트를 생성.
    생략된 블록은 요약 주석으로 대체.
    """
    # 청크를 원본 순서(line_start 기준)대로 정렬
    all_selected = sorted(
        selection.must_include + selection.context_include,
        key=lambda c: c.get('line_start', 0),
    )

    rtl_parts: list[str] = []
    prev_end = 0
    for chunk in all_selected:
        # 생략 구간이 있으면 요약 주석 삽입
        if chunk['line_start'] > prev_end + 1 and prev_end > 0:
            gap_omitted = [
                c for c in selection.omitted
                if prev_end < c['line_start'] < chunk['line_start']
            ]
            if gap_omitted:
                lhs_list = []
                for c in gap_omitted:
                    lhs_list.extend(c['lhs'][:2])
                rtl_parts.append(
                    f"    // [omitted: {len(gap_omitted)} block(s), "
                    f"drives: {', '.join(lhs_list) or '—'} — copy from origin.v unchanged]"
                )
        rtl_parts.append(chunk['text'])
        prev_end = chunk['line_end']

    rtl_context = '\n\n'.join(rtl_parts)

    # 토큰 정보 주석
    budget_note = (
        f"// Context: {selection.estimated_tokens} est. tokens | "
        f"{len(selection.omitted)} block(s) omitted"
    )

    prompt_parts = [
        "You are an RTL engineer. Generate a new complete Verilog module based on the deltas.",
        "Apply ALL changes from the new spec. For omitted blocks, copy them unchanged from the original.",
        "",
        "=== Original RTL (diff-scoped, key blocks only) ===",
        budget_note,
        rtl_context,
    ]

    if selection.omitted_summary:
        prompt_parts += [
            "",
            "=== Omitted Blocks (copy unchanged) ===",
            selection.omitted_summary,
        ]

    if uarch_origin is not None:
        prompt_parts += ["", "=== Micro-architecture (origin) ===", _read(uarch_origin)]
    if uarch_new is not None:
        prompt_parts += ["=== Micro-architecture (new) ===", _read(uarch_new)]
    prompt_parts += [
        "",
        "=== Algorithm (origin) ===",
        _read(algo_origin),
        "=== Algorithm (new) ===",
        _read(algo_new),
        "",
        "=== Requirements ===",
        "- Output the COMPLETE Verilog module (all ports + all blocks, including omitted ones).",
        "- Keep unchanged blocks exactly as in origin.v.",
        "- Implement every behavioral delta from the new spec.",
        "- No Markdown fences, no commentary. Synthesizable Verilog only.",
        "- Ensure the module terminates with 'endmodule'.",
    ]

    return '\n'.join(prompt_parts)
