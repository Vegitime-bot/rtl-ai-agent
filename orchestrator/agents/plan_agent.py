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

    # 1~2문장 action plan은 짧은 출력 — 512 토큰으로 제한
    PLAN_MAX_TOKENS = 512

    for module in rtl_modules:
        title = f"Review {module['module']}"
        detail = f"Check signals: {', '.join(p['name'] for p in module['ports'])}"
        if call_llm is not None:
            action = call_llm(
                f"Generate a concise natural-language action plan (1-2 sentences) for: {title}\nDetails: {detail}",
                model_cfg,
                system_prompt="You are an RTL design assistant. Be concise.",
                max_tokens=PLAN_MAX_TOKENS,
            )
        else:
            action = title
        plan.append(PlanItem(title=title, detail=detail, action=action))

    if spec_findings:
        title = "Address spec deltas"
        detail = "; ".join(spec_findings)
        if call_llm is not None:
            action = call_llm(
                f"Generate a concise natural-language action plan (1-2 sentences) for: {title}\nDetails: {detail}",
                model_cfg,
                system_prompt="You are an RTL design assistant. Be concise.",
                max_tokens=PLAN_MAX_TOKENS,
            )
        else:
            action = title
        plan.append(PlanItem(title=title, detail=detail, action=action))

    if graph_notes:
        for note in graph_notes:
            title = "Causal edge"
            if call_llm is not None:
                action = call_llm(
                    f"Generate a concise natural-language action plan (1-2 sentences) for causal edge: {note}",
                    model_cfg,
                    system_prompt="You are an RTL design assistant. Be concise.",
                    max_tokens=PLAN_MAX_TOKENS,
                )
            else:
                action = title
            plan.append(PlanItem(title=title, detail=note, action=action))

    return plan
