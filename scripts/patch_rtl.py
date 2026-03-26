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
    patches = [{"original": str, "replacement": str, "chunk": dict(optional)}, ...]

    치환 우선순위:
    1. chunk의 line_start/line_end 기반 위치 치환 (가장 안정적)
    2. 문자열 완전일치 치환 (fallback)
    3. 공백 정규화 후 일치 치환 (fallback)
    4. 모두 실패 시 경고 후 원본 유지

    line 기반 패치는 뒤에서부터 적용해 앞 패치가 line 번호를 밀지 않도록 함.
    """
    import re

    # chunk 정보 있는 패치를 line 기반으로 처리 (역순으로 적용)
    line_patches = [(i, p) for i, p in enumerate(patches) if p.get("chunk")]
    str_patches  = [(i, p) for i, p in enumerate(patches) if not p.get("chunk")]
    applied_indices: set[int] = set()

    lines = rtl_text.splitlines(keepends=True)

    # line 기반 치환 (역순: 뒤 라인부터 처리해야 앞 라인 번호가 안 밀림)
    for idx, patch in sorted(line_patches, key=lambda x: -(x[1]["chunk"].get("line_start", 0))):
        chunk = patch["chunk"]
        pos = find_block(rtl_text, chunk)
        print(f"[patch_rtl] line기반 치환 시도: L{chunk.get('line_start')}-{chunk.get('line_end')} → pos={pos}")
        if pos is None:
            print(f"[patch_rtl] ❌ find_block 실패 (라인 범위 초과?)")
            continue
        start, end = pos
        replacement = patch.get("replacement", "")
        if not replacement.endswith("\n"):
            replacement += "\n"
        print(f"[patch_rtl] ✅ line기반 치환 성공: chars {start}-{end} → {len(replacement)}chars")
        rtl_text = rtl_text[:start] + replacement + rtl_text[end:]
        applied_indices.add(idx)

    # 문자열 기반 치환 (chunk 없는 패치 + line 치환 실패한 것)
    remaining = [(i, p) for i, p in enumerate(patches) if i not in applied_indices]
    applied = len(applied_indices)

    for idx, patch in remaining:
        original = patch.get("original", "")
        replacement = patch.get("replacement", "")
        if not original:
            continue

        # 1차: 완전일치
        if original in rtl_text:
            rtl_text = rtl_text.replace(original, replacement, 1)
            applied += 1
            continue

        # 2차: 공백 정규화 후 일치
        def _norm(s: str) -> str:
            return re.sub(r"[ \t]+", " ", s.strip())

        norm_orig = _norm(original)
        norm_text = _norm(rtl_text)
        if norm_orig in norm_text:
            # 정규화된 위치를 원본에서 찾아 치환
            start = norm_text.index(norm_orig)
            end = start + len(norm_orig)
            # 원본 텍스트에서 대응 위치 복원 (근사)
            ratio = len(rtl_text) / max(len(norm_text), 1)
            raw_start = int(start * ratio)
            raw_end = int(end * ratio)
            # 앞뒤로 검색 범위 확장해 실제 블록 경계 찾기
            search_start = max(0, raw_start - 200)
            search_end = min(len(rtl_text), raw_end + 200)
            snippet = rtl_text[search_start:search_end]
            norm_snippet = _norm(snippet)
            if norm_orig in norm_snippet:
                s_idx = norm_snippet.index(norm_orig)
                # snippet에서 s_idx 위치의 원본 offset 복원
                cum = 0
                raw_idx = 0
                for ci, ch in enumerate(snippet):
                    if _norm(snippet[ci:ci+1]) and cum >= s_idx:
                        raw_idx = ci
                        break
                    if _norm(snippet[ci:ci+1]):
                        cum += len(_norm(snippet[ci:ci+1]))
                abs_start = search_start + raw_idx
                abs_end = abs_start + len(original)
                rtl_text = rtl_text[:abs_start] + replacement + rtl_text[abs_end:]
                applied += 1
                continue

        warnings.warn(
            f"[patch_rtl] 블록 치환 실패 — 원본에서 해당 텍스트를 찾을 수 없음 "
            f"(첫 40자: {original[:40]!r}). 원본 유지.",
            stacklevel=2,
        )

    print(f"[patch_rtl] {applied}/{len(patches)} 블록 치환 완료")
    return rtl_text
