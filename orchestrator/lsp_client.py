"""
orchestrator/lsp_client.py
──────────────────────────
ai-verilog-lsp HTTP 엔드포인트 클라이언트.

LSP 서버(HTTP mode)에서 RTL 모듈의 구조 정보(포트, 시그널, 동작)를
가져와 LLM 프롬프트 컨텍스트로 변환한다.

사용:
    from lsp_client import get_rtl_context, format_lsp_context

설정:
    환경변수 LSP_URL (기본: http://127.0.0.1:7342)
    또는 model yaml의 lsp_url 키
"""
from __future__ import annotations

import os
import warnings
from pathlib import Path
from typing import Any


_DEFAULT_LSP_URL = "http://127.0.0.1:7342"


def _lsp_url(cfg: dict | None = None) -> str:
    return (
        (cfg or {}).get("lsp_url")
        or os.environ.get("LSP_URL", _DEFAULT_LSP_URL)
    )


def get_spec_summary(
    rtl_file: Path,
    module_name: str | None = None,
    cfg: dict | None = None,
    timeout: int = 10,
) -> dict | None:
    """
    LSP /spec-summary 엔드포인트를 호출해 모듈 구조 정보를 반환.
    LSP 서버가 없거나 오류 시 None 반환 (graceful skip).

    반환 스키마 (SpecSummary):
        module, description, ports, parameters, behaviors, notes
    """
    try:
        import requests  # type: ignore
    except ImportError:
        warnings.warn("[lsp] requests 패키지 없음, LSP skip", stacklevel=2)
        return None

    url = _lsp_url(cfg).rstrip("/") + "/spec-summary"
    payload: dict[str, Any] = {"uri": rtl_file.resolve().as_uri()}
    if module_name:
        payload["moduleName"] = module_name

    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        if resp.status_code == 200:
            return resp.json()
        warnings.warn(
            f"[lsp] /spec-summary {resp.status_code}: {resp.text[:200]}",
            stacklevel=2,
        )
        return None
    except Exception as exc:
        warnings.warn(f"[lsp] LSP 서버 연결 실패, skip: {exc}", stacklevel=2)
        return None


def get_rtl_context(
    rtl_files: list[Path],
    cfg: dict | None = None,
) -> list[dict]:
    """
    여러 RTL 파일에 대해 LSP spec-summary를 조회해 리스트로 반환.
    실패한 파일은 조용히 스킵.
    """
    results = []
    for rtl_file in rtl_files:
        summary = get_spec_summary(rtl_file, cfg=cfg)
        if summary:
            summary["_source_file"] = str(rtl_file)
            results.append(summary)
    return results


def format_lsp_context(summaries: list[dict]) -> str:
    """
    SpecSummary 리스트를 LLM 프롬프트용 텍스트로 변환.
    """
    if not summaries:
        return ""

    lines = ["## RTL Module Context (from LSP)"]
    for s in summaries:
        module = s.get("module", "unknown")
        desc = s.get("description", "")
        lines.append(f"\n### Module: {module}")
        if desc:
            lines.append(f"Description: {desc}")

        ports = s.get("ports", [])
        if ports:
            lines.append("Ports:")
            for p in ports:
                width = p.get("width", "1")
                direction = p.get("direction", "")
                purpose = p.get("purpose", "")
                lines.append(f"  - {p['name']} [{direction}, {width}]: {purpose}")

        behaviors = s.get("behaviors", [])
        if behaviors:
            lines.append("Behaviors:")
            for b in behaviors:
                lines.append(f"  - {b}")

        notes = s.get("notes", [])
        if notes:
            lines.append("Notes:")
            for n in notes:
                lines.append(f"  - {n}")

    return "\n".join(lines)
