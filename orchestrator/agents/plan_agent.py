"""plan_agent — 독립 에이전트

입력 (파일): build/findings.json  (spec_agent 출력)
             rtl_ast.json          (파서 출력)

출력 (파일): build/plan.json
  [{"title": "...", "detail": "...", "action": "..."}]

LLM 컨텍스트: findings 요약문(짧은 텍스트)만 참조.
RTL 원문, algo, graph 등 다른 단계 원자료를 프롬프트에 포함하지 않는다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


@dataclass
class PlanItem:
    title: str
    detail: str
    action: str = ""


# 플랜 생성 전용 토큰 상한 — RTL 생성용 max_tokens와 독립
_PLAN_MAX_TOKENS_DEFAULT = 256


def build_plan(
    rtl_modules: List[dict],
    spec_findings: List[str],
    graph_notes: List[str] | None = None,
    model_cfg: dict | None = None,
    output_path: Path | None = None,
) -> List[PlanItem]:
    """
    spec_findings: SpecFinding.summary 문자열 목록 (요약된 짧은 텍스트만).
    RTL 원문이나 알고리즘 파일 내용을 받지 않음.

    output_path 지정 시 build/plan.json으로 저장.
    """
    if model_cfg:
        try:
            from llm_utils import call_llm  # type: ignore
        except ImportError:
            call_llm = None
    else:
        call_llm = None

    plan_max = model_cfg.get("max_tokens", 2048) if model_cfg else 2048

    def _safe_action(prompt_text: str, fallback: str) -> str:
        """독립 LLM 호출 — 이전 단계 원자료 없이 요약 텍스트만으로 플랜 생성."""
        if call_llm is None:
            return fallback
        try:
            result = call_llm(
                prompt_text,
                model_cfg,
                system_prompt=(
                    "You are an RTL design assistant. "
                    "Generate a concise 1-2 sentence action plan. "
                    "Reply with the action plan only."
                ),
                max_tokens=plan_max,
            )
            return result.strip() if result else fallback
        except Exception:
            return fallback

    plan: List[PlanItem] = []

    for module in rtl_modules:
        title = f"Review {module['module']}"
        detail = f"Check signals: {', '.join(p['name'] for p in module.get('ports', []))}"
        action = _safe_action(
            f"Action plan for reviewing RTL module '{module['module']}'.\nSignals: {detail}",
            fallback=title,
        )
        plan.append(PlanItem(title=title, detail=detail, action=action))

    if spec_findings:
        title = "Address spec deltas"
        # findings는 이미 요약된 짧은 문자열 — 원자료 아님
        detail = "; ".join(f for f in spec_findings if f)
        # detail이 너무 길면 앞부분만 (plan은 짧아야 함)
        detail_truncated = detail[:2000] + ("..." if len(detail) > 2000 else "")
        action = _safe_action(
            f"Action plan for spec deltas:\n{detail_truncated}",
            fallback=title,
        )
        plan.append(PlanItem(title=title, detail=detail, action=action))

    if graph_notes:
        for note in graph_notes:
            action = _safe_action(
                f"Action plan for causal edge: {note}",
                fallback="Causal edge",
            )
            plan.append(PlanItem(title="Causal edge", detail=note, action=action))

    # 파일 I/O 인터페이스
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps([p.__dict__ for p in plan], indent=2, ensure_ascii=False)
        )

    return plan


def load_plan(path: Path) -> List[PlanItem]:
    """build/plan.json → PlanItem 목록 복원."""
    data = json.loads(path.read_text())
    return [PlanItem(**d) for d in data]
