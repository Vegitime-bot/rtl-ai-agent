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

    치환 방식:
    - chunk의 line_start/line_end 기반으로 lines 배열에서 직접 슬라이스 치환
    - lines 배열을 수정하므로 라인 번호 기준은 항상 원본 기준으로 계산 후
      오프셋을 누적해 보정 → 앞 패치가 뒤 패치의 라인 번호를 밀지 않음
    - chunk 없는 패치: 문자열 완전일치 fallback
    """
    # chunk 있는 패치를 line_start 오름차순 정렬 후 라인 오프셋 누적 보정
    line_patches = [(i, p) for i, p in enumerate(patches) if p.get("chunk")]
    str_patches  = [(i, p) for i, p in enumerate(patches) if not p.get("chunk")]
    applied_indices: set[int] = set()

    lines = rtl_text.splitlines(keepends=True)
    line_offset = 0  # 앞 패치로 인해 밀린 라인 수 누적

    for idx, patch in sorted(line_patches, key=lambda x: x[1]["chunk"].get("line_start", 0)):
        chunk = patch["chunk"]
        # 원본 라인 번호에 누적 오프셋 적용
        raw_start = chunk.get("line_start", 1) - 1  # 0-indexed
        raw_end   = chunk.get("line_end", raw_start + 1)
        adj_start = raw_start + line_offset
        adj_end   = raw_end   + line_offset

        if adj_start < 0 or adj_start >= len(lines):
            print(f"[patch_rtl] ❌ find_block 실패: L{raw_start+1}-{raw_end} (adj {adj_start}-{adj_end}, total {len(lines)} lines)")
            continue

        adj_end = min(adj_end, len(lines))
        replacement = patch.get("replacement", "")
        if replacement and not replacement.endswith("\n"):
            replacement += "\n"
        replacement_lines = replacement.splitlines(keepends=True)

        orig_count = adj_end - adj_start
        new_count  = len(replacement_lines)
        lines[adj_start:adj_end] = replacement_lines
        line_offset += new_count - orig_count

        print(f"[patch_rtl] ✅ line기반 치환: L{raw_start+1}-{raw_end} "
              f"({orig_count}lines → {new_count}lines, offset={line_offset})")
        applied_indices.add(idx)

    rtl_text = "".join(lines)
    applied = len(applied_indices)

    # chunk 없는 패치: 문자열 완전일치 fallback
    for idx, patch in str_patches:
        original = patch.get("original", "")
        replacement = patch.get("replacement", "")
        if not original:
            continue
        if original in rtl_text:
            rtl_text = rtl_text.replace(original, replacement, 1)
            applied += 1
        else:
            warnings.warn(
                f"[patch_rtl] 블록 치환 실패 — 원본에서 해당 텍스트를 찾을 수 없음 "
                f"(첫 40자: {original[:40]!r}). 원본 유지.",
                stacklevel=2,
            )

    print(f"[patch_rtl] {applied}/{len(patches)} 블록 치환 완료")
    return rtl_text
