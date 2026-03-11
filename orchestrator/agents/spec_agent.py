from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class SpecFinding:
    source: str
    summary: str


def analyze(ma_chunks: List[dict], pseudo_diff: str) -> List[SpecFinding]:
    findings: List[SpecFinding] = []
    for chunk in ma_chunks:
        findings.append(SpecFinding(source=chunk["ref"], summary=chunk["content"][:200]))
    if pseudo_diff:
        findings.append(SpecFinding(source="pseudo_diff", summary=pseudo_diff[:200]))
    return findings
