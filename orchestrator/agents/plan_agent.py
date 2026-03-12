from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class PlanItem:
    title: str
    detail: str


def build_plan(rtl_modules: List[dict], spec_findings: List[str], graph_notes: List[str] | None = None) -> List[PlanItem]:
    plan: List[PlanItem] = []
    for module in rtl_modules:
        plan.append(PlanItem(title=f"Review {module['module']}", detail=f"Check signals: {', '.join(p['name'] for p in module['ports'])}"))
    if spec_findings:
        plan.append(PlanItem(title="Address spec deltas", detail="; ".join(spec_findings)))
    if graph_notes:
        for note in graph_notes:
            plan.append(PlanItem(title="Causal edge", detail=note))
    return plan
