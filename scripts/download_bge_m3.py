#!/usr/bin/env python3
"""
scripts/download_bge_m3.py
───────────────────────────
BAAI/bge-m3 모델을 HuggingFace Hub 에서 프로젝트 내부(models/bge-m3/)로 다운로드.

인터넷이 되는 환경(개발 PC)에서 1회 실행 후,
models/bge-m3/ 디렉토리를 사내망 서버에 그대로 복사한다.

사용:
  python scripts/download_bge_m3.py
  python scripts/download_bge_m3.py --dest models/bge-m3   # (기본값)
  python scripts/download_bge_m3.py --dest /data/models/bge-m3
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DEST = _PROJECT_ROOT / "models" / "bge-m3"


def main() -> None:
    parser = argparse.ArgumentParser(description="Download BAAI/bge-m3 to local directory")
    parser.add_argument("--dest", type=Path, default=_DEFAULT_DEST,
                        help=f"저장 경로 (기본: {_DEFAULT_DEST})")
    parser.add_argument("--repo-id", type=str, default="BAAI/bge-m3",
                        help="HuggingFace 모델 ID")
    args = parser.parse_args()

    try:
        from huggingface_hub import snapshot_download  # type: ignore
    except ImportError:
        print("huggingface_hub 가 없습니다. pip install huggingface_hub==0.23.4")
        sys.exit(1)

    print(f"[download] {args.repo_id} → {args.dest}")
    args.dest.mkdir(parents=True, exist_ok=True)

    local_dir = snapshot_download(
        repo_id=args.repo_id,
        local_dir=str(args.dest),
        local_dir_use_symlinks=False,   # 심볼릭링크 없이 실제 파일로 저장
        ignore_patterns=["*.msgpack", "flax_model*", "tf_model*", "rust_model*"],
    )
    print(f"[download] 완료: {local_dir}")
    print("이제 models/bge-m3/ 디렉토리를 사내망 서버에 복사하세요.")


if __name__ == "__main__":
    main()
