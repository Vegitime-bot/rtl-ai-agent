"""
scripts/patch_rtl.py
─────────────────────
RTL 텍스트에서 블록을 식별하고 치환하는 유틸리티.

함수:
  find_block(rtl_text, chunk) -> (start_pos, end_pos) | None
  apply_patch(rtl_text, patches) -> str
"""
from __future__ import annotations

import warnings


def find_block(rtl_text: str, chunk: dict) -> tuple[int, int] | None:
    """
    chunk의 line_start/line_end 기반으로 원본 RTL에서 블록 위치를 찾는다.
    반환: (start_char_pos, end_char_pos) or None
    """
    lines = rtl_text.splitlines(keepends=True)
    line_start = chunk.get("line_start", 1) - 1  # 0-indexed
    line_end = chunk.get("line_end", line_start + 1)

    if line_start < 0 or line_start >= len(lines):
        return None
    line_end = min(line_end, len(lines))

    start_pos = sum(len(l) for l in lines[:line_start])
    end_pos = sum(len(l) for l in lines[:line_end])
    return start_pos, end_pos


def apply_patch(rtl_text: str, patches: list[dict]) -> str:
    """
    patches = [{"original": str, "replacement": str}, ...]
    원본 텍스트에서 original을 replacement로 순서대로 치환.
    치환 실패 시 경고만 출력하고 원본 유지.
    """
    result = rtl_text
    applied = 0
    for patch in patches:
        original = patch.get("original", "")
        replacement = patch.get("replacement", "")
        if not original:
            continue
        if original in result:
            result = result.replace(original, replacement, 1)
            applied += 1
        else:
            warnings.warn(
                f"[patch_rtl] 블록 치환 실패 — 원본에서 해당 텍스트를 찾을 수 없음 "
                f"(첫 40자: {original[:40]!r}). 원본 유지.",
                stacklevel=2,
            )
    print(f"[patch_rtl] {applied}/{len(patches)} 블록 치환 완료")
    return result
