#!/usr/bin/env python3
"""
scripts/diff_pseudo.py
───────────────────────
두 알고리즘 스펙(origin / new)의 통합 diff를 생성한다.

단일 파일 모드 (기존):
  python scripts/diff_pseudo.py old.py new.py output.json

디렉토리 모드 (다중 파일):
  python scripts/diff_pseudo.py inputs/algorithm/origin/ inputs/algorithm/new/ output.json

  - origin/ 과 new/ 의 파일명을 매칭한다.
  - origin에만 있는 파일 → 삭제된 파일로 처리 (전체 줄을 '-' diff로)
  - new에만 있는 파일   → 신규 파일로 처리 (전체 줄을 '+' diff로)
  - 양쪽 모두 있는 파일 → 통합 diff
"""
from __future__ import annotations

import argparse
import difflib
import json
from pathlib import Path


_PY_SUFFIXES = {".py", ".txt", ".sv", ".v"}


def _collect_files(path: Path) -> dict[str, Path]:
    """디렉토리면 하위 파일 목록(stem→path), 파일이면 {path.name: path}."""
    if path.is_dir():
        return {
            f.name: f
            for f in sorted(path.iterdir())
            if f.is_file() and f.suffix in _PY_SUFFIXES
        }
    elif path.is_file():
        return {path.name: path}
    else:
        raise FileNotFoundError(f"경로를 찾을 수 없습니다: {path}")


def _diff_texts(old_lines: list[str], new_lines: list[str],
                fromfile: str = "origin", tofile: str = "new") -> list[str]:
    return list(difflib.unified_diff(old_lines, new_lines,
                                     fromfile=fromfile, tofile=tofile, lineterm=""))


def build_diff(origin_path: Path, new_path: Path) -> dict:
    """origin / new 경로(파일 또는 디렉토리)를 받아 diff payload dict를 반환."""
    origin_files = _collect_files(origin_path)
    new_files = _collect_files(new_path)

    all_names = sorted(set(origin_files) | set(new_files))
    all_diffs: list[str] = []
    file_summaries: list[dict] = []

    for name in all_names:
        o_path = origin_files.get(name)
        n_path = new_files.get(name)

        if o_path and n_path:
            old_lines = o_path.read_text(encoding="utf-8").splitlines()
            new_lines = n_path.read_text(encoding="utf-8").splitlines()
            status = "modified"
        elif o_path:
            old_lines = o_path.read_text(encoding="utf-8").splitlines()
            new_lines = []
            status = "deleted"
        else:
            old_lines = []
            new_lines = n_path.read_text(encoding="utf-8").splitlines()  # type: ignore[union-attr]
            status = "added"

        file_diff = _diff_texts(old_lines, new_lines,
                                fromfile=f"origin/{name}", tofile=f"new/{name}")
        all_diffs.extend(file_diff)
        file_summaries.append({
            "file": name,
            "status": status,
            "diff_lines": len(file_diff),
        })
        print(f"[diff_pseudo] {name}: {status} ({len(file_diff)} diff lines)")

    return {
        "origin": str(origin_path),
        "new": str(new_path),
        "files": file_summaries,
        "diff": all_diffs,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate unified diff between origin/new algorithm files or directories"
    )
    parser.add_argument("old", type=Path,
                        help="origin 파일 또는 inputs/algorithm/origin/ 디렉토리")
    parser.add_argument("new", type=Path,
                        help="new 파일 또는 inputs/algorithm/new/ 디렉토리")
    parser.add_argument("output", type=Path,
                        help="출력 JSON 경로 (예: build/pseudo_diff.json)")
    args = parser.parse_args()

    payload = build_diff(args.old, args.new)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    total = len(payload["diff"])
    print(f"[diff_pseudo] total diff {total} lines → {args.output}")


if __name__ == "__main__":
    main()
