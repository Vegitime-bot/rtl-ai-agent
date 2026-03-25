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

    # 요약 작업 출력 토큰 상한 — 모델이 장황하게 출력하는 경우를 대비해 1024로 설정
    SUMMARY_MAX_TOKENS = 1024

    findings: List[SpecFinding] = []
    for chunk in ma_chunks:
        content = chunk["content"]
        if call_llm is not None:
            try:
                summary = call_llm(
                    f"Summarize the following RTL spec chunk in 2-3 sentences:\n{content}",
                    model_cfg,
                    system_prompt="You are an RTL design assistant. Be concise. Reply in 2-3 sentences only.",
                    max_tokens=SUMMARY_MAX_TOKENS,
                )
            except Exception:
                # LLM 실패 시 텍스트 직접 truncate
                summary = content[:400]
        else:
            summary = content[:400]
        findings.append(SpecFinding(source=chunk["ref"], summary=summary))

    if pseudo_diff:
        if call_llm is not None:
            try:
                summary = call_llm(
                    f"Summarize the following RTL pseudo-diff in 2-3 sentences:\n{pseudo_diff}",
                    model_cfg,
                    system_prompt="You are an RTL design assistant. Be concise. Reply in 2-3 sentences only.",
                    max_tokens=SUMMARY_MAX_TOKENS,
                )
            except Exception:
                summary = pseudo_diff[:400]
        else:
            summary = pseudo_diff[:400]
        findings.append(SpecFinding(source="pseudo_diff", summary=summary))

    return findings
