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

    # 분석 요약은 2~3문장 → 512토큰으로 충분. yaml max_tokens(RTL 생성용)를 그대로 쓰지 않음
    SUMMARY_MAX_TOKENS = model_cfg.get("analysis_max_tokens", 512) if model_cfg else 512
    # 입력 청크를 LLM에 넣기 전 최대 글자수 제한 (4자 ≈ 1토큰, 3000토큰 분량)
    INPUT_CHAR_LIMIT = 12000

    def _safe_summary(text: str, source: str) -> str:
        """LLM 요약 시도, 실패하거나 None 반환 시 텍스트 직접 truncate."""
        truncated = text[:INPUT_CHAR_LIMIT]
        if call_llm is None:
            return truncated[:400]
        try:
            result = call_llm(
                f"Summarize the following RTL spec in 2-3 sentences:\n{truncated}",
                model_cfg,
                system_prompt="You are an RTL design assistant. Be concise. Reply in 2-3 sentences only.",
                max_tokens=SUMMARY_MAX_TOKENS,
            )
            return result if result else truncated[:400]
        except Exception:
            return truncated[:400]

    findings: List[SpecFinding] = []
    for chunk in ma_chunks:
        content = chunk["content"]
        summary = _safe_summary(content, chunk["ref"])
        findings.append(SpecFinding(source=chunk["ref"], summary=summary))

    if pseudo_diff:
        summary = _safe_summary(pseudo_diff, "pseudo_diff")
        findings.append(SpecFinding(source="pseudo_diff", summary=summary))

    return findings
