from __future__ import annotations

from pathlib import Path
from typing import List

from .spec_agent import SpecFinding
from .plan_agent import PlanItem


def write_report(path: Path, findings: List[SpecFinding], plan: List[PlanItem], llm_summary: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write("# Analysis Report\n\n")
        f.write("## Spec Findings\n")
        for item in findings:
            f.write(f"- **{item.source}**: {item.summary}\n")
        f.write("\n## Action Plan\n")
        for item in plan:
            f.write(f"- {item.title}: {item.detail}\n")
        if llm_summary:
            f.write("\n## LLM Summary\n")
            f.write(llm_summary.strip() + "\n")
