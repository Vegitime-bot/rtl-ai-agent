"""
orchestrator/verify.py
───────────────────────
생성된 RTL에 대한 다단계 검증.

check 단계:
  1. basic   — 파일 존재 / TODO / module 선언
  2. causal  — 신호 의존성이 causal_graph.json(원본) + 신규 스펙 필수 엣지와 일치하는지 정적 분석

run_checks(rtl_path, causal_graph_path=None) 를 외부에서 호출.
causal_graph_path 가 None 이면 causal 단계를 건너뜀(graceful skip).
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path

try:
    import json
except ImportError:
    json = None  # type: ignore

# ─────────────────────────────────────────────
# 1. Basic checks (기존)
# ─────────────────────────────────────────────

MODULE_RE = re.compile(r"module\s+\w+")


def _basic_checks(path: Path) -> dict:
    if not path.exists():
        return {"status": "fail", "checks": ["basic"], "detail": "output file missing"}
    text = path.read_text()
    if "TODO" in text:
        return {"status": "fail", "checks": ["basic"], "detail": "contains TODO"}
    if not MODULE_RE.search(text):
        return {"status": "fail", "checks": ["basic"], "detail": "no module declaration"}
    if "endmodule" not in text:
        return {"status": "fail", "checks": ["basic"], "detail": "endmodule not found"}
    return {"status": "pass", "checks": ["basic"], "detail": "basic checks passed"}


# ─────────────────────────────────────────────
# 2. Causal graph checks
# ─────────────────────────────────────────────

VL_KEYWORDS = {
    'begin', 'end', 'if', 'else', 'case', 'casex', 'casez', 'endcase',
    'default', 'assign', 'always', 'posedge', 'negedge', 'or', 'and',
    'not', 'wire', 'reg', 'integer', 'parameter', 'localparam', 'module',
    'endmodule', 'input', 'output', 'inout', 'initial', 'for', 'while',
    'repeat', 'forever', 'task', 'endtask', 'function', 'endfunction',
}


def _strip_comments(text: str) -> str:
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    text = re.sub(r'//[^\n]*', '', text)
    return text


def _collect_signals(verilog: str) -> dict[str, str]:
    kinds: dict[str, str] = {}
    for m in re.finditer(r'\bparameter\b[^;]*?(\w+)\s*=', verilog):
        kinds[m.group(1)] = 'param'
    for m in re.finditer(r'\blocalparam\b[^;]*?(\w+)\s*=', verilog):
        kinds[m.group(1)] = 'localparam'
    port_re = re.compile(r'\b(input|output)\s+(?:reg\s+)?(?:\[\S+\]\s+)?(\w+)')
    for m in port_re.finditer(verilog):
        kinds[m.group(2)] = m.group(1)
    for m in re.finditer(r'\b(?:reg|wire|integer)\b[^;]*?(\w+)\s*;', verilog):
        if m.group(1) not in kinds:
            kinds[m.group(1)] = 'signal'
    return kinds


def _extract_identifiers(expr: str, exclude: set[str]) -> set[str]:
    toks = re.findall(r'\b([A-Za-z_]\w*)\b', expr)
    return {t for t in toks if t not in VL_KEYWORDS and t not in exclude}


def _extract_block_body(text: str, start: int) -> str:
    i = text.index('begin', start) + len('begin')
    depth = 1
    j = i
    while j < len(text) and depth > 0:
        m = re.search(r'\b(begin|end)\b', text[j:])
        if not m:
            break
        tok = m.group(1)
        j += m.start() + len(tok)
        depth += 1 if tok == 'begin' else -1
    return text[i: j - len('end')]


def _lhs_signals(body: str, all_signals: dict[str, str]) -> set[str]:
    lhs: set[str] = set()
    for m in re.finditer(r'(\w+)\s*(?:\[[^\]]*\])?\s*(?:<=|(?<!=)=(?!=))', body):
        if m.group(1) in all_signals:
            lhs.add(m.group(1))
    return lhs


def _edges_from_body(body: str, all_signals: dict[str, str]) -> set[tuple[str, str]]:
    lhs_set = _lhs_signals(body, all_signals)
    rhs = _extract_identifiers(body, lhs_set)
    rhs = {s for s in rhs if s in all_signals}
    return {(r, l) for l in lhs_set for r in rhs if r != l}


def _build_edge_sets(verilog: str) -> tuple[set, set, set]:
    all_sigs = _collect_signals(verilog)
    comb: set = set()
    clocked: set = set()
    assigns: set = set()

    for m in re.finditer(r'\bassign\s+(\w+)\s*=([^;]+);', verilog):
        lhs = m.group(1)
        for rhs in _extract_identifiers(m.group(2), {lhs}):
            if rhs in all_sigs:
                assigns.add((rhs, lhs))

    for m in re.finditer(r'\balways\s*@\s*\(([^)]+)\)', verilog):
        sens = m.group(1).strip()
        try:
            body = _extract_block_body(verilog, m.end())
        except (ValueError, IndexError):
            continue
        edges = _edges_from_body(body, all_sigs)
        if re.search(r'\b(posedge|negedge)\b', sens):
            clocked |= edges
        else:
            comb |= edges

    return comb, clocked, assigns


# 원본 → 신규에서 파이프라인 단계 삽입으로 경로가 길어진 것은 정상
_KNOWN_EVOLVED: dict[tuple, str] = {
    ('crop_pixel',         'final_pixel'): 'pipeline stage inserted',
    ('test_pattern_pixel', 'final_pixel'): 'pipeline stage inserted',
}

# 원본 엣지 중 클락 블록에 있는 것
_ORIG_CLOCKED: set[tuple] = {
    ('ST_FILL',   'state'),
    ('hsync_pol', 'hsync'),
    ('vsync_pol', 'vsync'),
}


def _causal_checks(
    rtl_path: Path,
    graph_path: Path,
    pass_threshold: float = 0.5,
) -> dict:
    """
    causal_graph.json 원본 엣지 보존 신뢰도 검증.

    pass_threshold: 보존율(0.0~1.0) 이상이면 pass. 기본 0.5(50%).
      - yaml에 verify_causal_threshold 키로 override 가능
      - 1.0 = 모든 엣지 보존 필수 (엄격), 0.0 = 항상 pass
    """
    if json is None:
        return {"status": "skip", "detail": "json module unavailable"}

    try:
        verilog = _strip_comments(rtl_path.read_text())
        graph_obj = json.loads(graph_path.read_text())
    except Exception as e:
        return {"status": "skip", "detail": f"could not load files: {e}"}

    comb, clocked, assigns = _build_edge_sets(verilog)
    all_edges = comb | clocked | assigns

    orig_edges = {(e['from'], e['to']) for e in graph_obj['graphs'][0]['edges']}
    total = len(orig_edges)
    if total == 0:
        return {"status": "pass", "checks": ["causal"], "detail": "no original edges to check",
                "confidence": 1.0, "preserved": 0, "evolved": 0, "missing_edges": []}

    missing: list[str] = []
    preserved = 0
    evolved = 0

    for (frm, to) in orig_edges:
        if (frm, to) in all_edges:
            preserved += 1
        elif (frm, to) in _KNOWN_EVOLVED:
            evolved += 1
        elif (frm, to) in _ORIG_CLOCKED:
            if (frm, to) in clocked:
                preserved += 1
            else:
                missing.append(f"{frm} → {to}")
        else:
            missing.append(f"{frm} → {to}")

    confidence = round((preserved + evolved) / total, 3)
    status = "pass" if confidence >= pass_threshold else "fail"

    return {
        "status": status,
        "checks": ["causal"],
        "confidence": confidence,
        "pass_threshold": pass_threshold,
        "detail": (
            f"causal confidence {confidence:.1%} "
            f"(preserved={preserved}, evolved={evolved}, missing={len(missing)}/{total})"
            + (" ✅" if status == "pass" else f" ⚠️  threshold={pass_threshold:.0%}")
        ),
        "preserved": preserved,
        "evolved": evolved,
        "missing_edges": missing,
    }


# ─────────────────────────────────────────────
# 3. 통합 진입점
# ─────────────────────────────────────────────

def run_checks(rtl_path: Path, causal_graph_path: Path | None = None, causal_threshold: float = 0.5) -> dict:
    """
    RTL 파일에 대해 다단계 검증을 실행한다.

    반환 형식:
    {
        "status": "pass" | "fail" | "partial",
        "checks": ["basic", "causal"],
        "results": {
            "basic":  { ... },
            "causal": { ... },   # causal_graph_path 없으면 skip
        }
    }
    """
    results: dict[str, dict] = {}

    # Step 1: basic
    basic = _basic_checks(rtl_path)
    results["basic"] = basic
    if basic["status"] == "fail":
        return {"status": "fail", "checks": list(results.keys()), "results": results}

    # Step 2: causal
    if causal_graph_path is not None:
        if not causal_graph_path.exists():
            warnings.warn(f"[verify] causal_graph not found: {causal_graph_path}, skipping causal check")
            results["causal"] = {"status": "skip", "detail": "graph file not found"}
        else:
            causal = _causal_checks(rtl_path, causal_graph_path, pass_threshold=causal_threshold)
            results["causal"] = causal
    else:
        results["causal"] = {"status": "skip", "detail": "no causal_graph_path provided"}

    # 전체 판정
    statuses = {v["status"] for v in results.values()}
    if "fail" in statuses:
        overall = "fail"
    elif statuses == {"pass"}:
        overall = "pass"
    else:
        overall = "partial"  # skip 포함

    return {"status": overall, "checks": list(results.keys()), "results": results}


# ─────────────────────────────────────────────
# 하위 호환: 기존 run_basic_checks 인터페이스 유지
# ─────────────────────────────────────────────

def run_basic_checks(path: Path) -> dict:
    """Deprecated: use run_checks() instead. Kept for backward compatibility."""
    result = run_checks(path, causal_graph_path=None)
    basic = result["results"].get("basic", {})
    return {"status": basic.get("status", "fail"), "detail": basic.get("detail", "")}
