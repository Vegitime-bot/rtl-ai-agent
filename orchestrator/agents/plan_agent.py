from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class PlanItem:
    title: str
    detail: str
    action: str = ""


def build_plan(rtl_modules: List[dict], spec_findings: List[str], graph_notes: List[str] | None = None, model_cfg: dict | None = None) -> List[PlanItem]:
    plan: List[PlanItem] = []

    if model_cfg:
        try:
            from llm_utils import call_llm  # type: ignore
        except ImportError:
            call_llm = None
    else:
        call_llm = None

    PLAN_MAX_TOKENS = 512

    def _safe_action(prompt_text: str, fallback: str) -> str:
        if call_llm is None:
            return fallback
        try:
            result = call_llm(
                prompt_text,
                model_cfg,
                system_prompt="You are an RTL design assistant. Be concise.",
                max_tokens=PLAN_MAX_TOKENS,
            )
            return result if result else fallback
        except Exception:
            return fallback

    for module in rtl_modules:
        title = f"Review {module['module']}"
        detail = f"Check signals: {', '.join(p['name'] for p in module['ports'])}"
        action = _safe_action(
            f"Generate a concise natural-language action plan (1-2 sentences) for: {title}\nDetails: {detail}",
            fallback=title,
        )
        plan.append(PlanItem(title=title, detail=detail, action=action))

    if spec_findings:
        title = "Address spec deltas"
        detail = "; ".join(f for f in spec_findings if f)  # None 필터링
        action = _safe_action(
            f"Generate a concise natural-language action plan (1-2 sentences) for: {title}\nDetails: {detail}",
            fallback=title,
        )
        plan.append(PlanItem(title=title, detail=detail, action=action))

    if graph_notes:
        for note in graph_notes:
            title = "Causal edge"
            action = _safe_action(
                f"Generate a concise natural-language action plan (1-2 sentences) for causal edge: {note}",
                fallback=title,
            )
            plan.append(PlanItem(title=title, detail=note, action=action))

    return plan
