from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class PlanItem:
    title: str
    detail: str


def build_plan(rtl_modules: List[dict], spec_findings: List[str]) -> List[PlanItem]:
    plan: List[PlanItem] = []
    for module in rtl_modules:
        plan.append(PlanItem(title=f"Review {module['module']}", detail=f"Check signals: {', '.join(p['name'] for p in module['ports'])}"))
    if spec_findings:
        plan.append(PlanItem(title="Address spec deltas", detail="; ".join(spec_findings)))
    return plan
