from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class SpecFinding:
    source: str
    summary: str


def analyze(ma_chunks: List[dict], pseudo_diff: str, model_cfg: dict | None = None) -> List[SpecFinding]:
    if model_cfg:
        try:
            from llm_utils import call_llm  # type: ignore
        except ImportError:
            call_llm = None
    else:
        call_llm = None

    findings: List[SpecFinding] = []
    for chunk in ma_chunks:
        content = chunk["content"]
        if call_llm is not None:
            summary = call_llm(
                f"Summarize the following RTL spec chunk in 200 characters or less:\n{content}",
                model_cfg,
                system_prompt="You are an RTL design assistant. Be concise.",
            )
        else:
            summary = content[:200]
        findings.append(SpecFinding(source=chunk["ref"], summary=summary))

    if pseudo_diff:
        if call_llm is not None:
            summary = call_llm(
                f"Summarize the following RTL pseudo-diff in 200 characters or less:\n{pseudo_diff}",
                model_cfg,
                system_prompt="You are an RTL design assistant. Be concise.",
            )
        else:
            summary = pseudo_diff[:200]
        findings.append(SpecFinding(source="pseudo_diff", summary=summary))

    return findings
