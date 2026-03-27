"""spec_agent — 독립 에이전트

입력 (파일):
  - ma_chunks: list[dict]  (FAISS 검색 결과, 호출자가 메모리로 전달)
  - pseudo_diff: str

출력 (파일): build/findings.json
  [{"source": "...", "summary": "..."}]

LLM 컨텍스트: 자신이 담당하는 청크 1개씩만 처리.
이전/이후 단계 결과를 프롬프트에 포함하지 않는다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass
class SpecFinding:
    source: str
    summary: str


# 분석 요약용 토큰 상한 — RTL 생성용 max_tokens와 독립
_ANALYSIS_MAX_TOKENS_DEFAULT = 512
# 입력 청크 최대 글자 (4자 ≈ 1토큰, 3000토큰 분량)
_INPUT_CHAR_LIMIT = 12_000


def analyze(
    ma_chunks: List[dict],
    pseudo_diff: str,
    model_cfg: dict | None = None,
    output_path: Path | None = None,
) -> List[SpecFinding]:
    """
    각 청크를 독립된 LLM 호출로 요약.
    이전/이후 단계 컨텍스트를 프롬프트에 포함하지 않음.

    output_path 지정 시 build/findings.json으로 저장 (다음 단계 파일 I/O 인터페이스).
    """
    if model_cfg:
        try:
            from llm_utils import call_llm  # type: ignore
        except ImportError:
            call_llm = None
    else:
        call_llm = None

    summary_max = model_cfg.get("max_tokens", 2048) if model_cfg else 2048

    def _summarize(text: str) -> str:
        """청크 1개를 독립 LLM 호출로 요약. 다른 청크/단계 정보 없음."""
        truncated = text[:_INPUT_CHAR_LIMIT]
        if call_llm is None:
            return truncated[:400]
        try:
            result = call_llm(
                f"Summarize the following RTL spec change in 2-3 sentences:\n{truncated}",
                model_cfg,
                system_prompt=(
                    "You are an RTL design assistant. "
                    "Summarize the given spec text concisely in 2-3 sentences. "
                    "Do not include information from other sources."
                ),
                max_tokens=summary_max,
            )
            return result.strip() if result else truncated[:400]
        except Exception:
            return truncated[:400]

    findings: List[SpecFinding] = []

    for chunk in ma_chunks:
        summary = _summarize(chunk["content"])
        findings.append(SpecFinding(source=chunk.get("ref", ""), summary=summary))

    if pseudo_diff:
        summary = _summarize(pseudo_diff)
        findings.append(SpecFinding(source="pseudo_diff", summary=summary))

    # 파일 I/O 인터페이스: 다음 단계(plan_agent)가 파일로 읽어감
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps([f.__dict__ for f in findings], indent=2, ensure_ascii=False)
        )

    return findings


def load_findings(path: Path) -> List[SpecFinding]:
    """build/findings.json → SpecFinding 목록 복원 (plan_agent에서 사용)."""
    data = json.loads(path.read_text())
    return [SpecFinding(**d) for d in data]
