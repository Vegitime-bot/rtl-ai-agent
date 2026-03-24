"""
rag/model_paths.py
───────────────────
BGE-M3 모델 경로 해석 헬퍼.

우선순위:
  1. 환경변수  RTL_BGE_MODEL_DIR  (절대경로)
  2. 프로젝트 내부 디렉토리      models/bge-m3/
  3. HuggingFace Hub ID 폴백     BAAI/bge-m3  (인터넷 필요 — 사내망에선 사용 불가)

사내망 준비:
  - models/bge-m3/ 아래에 HuggingFace 모델 파일을 그대로 복사해 두면
    인터넷 없이 자동으로 로컬 경로를 사용한다.
  - 필요 파일: config.json, tokenizer*.json, *.safetensors (또는 pytorch_model.bin)

다운로드 예시 (인터넷 환경):
  python scripts/download_bge_m3.py          # 아래 스크립트 참고
  또는
  huggingface-cli download BAAI/bge-m3 --local-dir models/bge-m3 --local-dir-use-symlinks False
"""
from __future__ import annotations

import os
from pathlib import Path

# 프로젝트 루트: rag/ 의 부모
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 기본 로컬 모델 디렉토리
_DEFAULT_LOCAL = _PROJECT_ROOT / "models" / "bge-m3"

# HuggingFace Hub ID (폴백 전용)
_HUB_ID = "BAAI/bge-m3"


def resolve_bge_model_path() -> str:
    """
    BGE-M3 모델 경로 문자열을 반환한다.

    반환값은 BGEM3FlagModel(model_name_or_path=...) 에 바로 넘길 수 있다.
    """
    # 1) 환경변수 우선
    env_path = os.environ.get("RTL_BGE_MODEL_DIR", "").strip()
    if env_path:
        p = Path(env_path)
        if not p.exists():
            raise FileNotFoundError(
                f"RTL_BGE_MODEL_DIR 가 가리키는 경로가 존재하지 않습니다: {p}"
            )
        return str(p)

    # 2) 프로젝트 내부 로컬 경로
    if _DEFAULT_LOCAL.exists() and _is_model_complete(_DEFAULT_LOCAL):
        return str(_DEFAULT_LOCAL)

    # 3) HuggingFace Hub 폴백 (경고 출력)
    import warnings
    warnings.warn(
        f"[model_paths] BGE-M3 로컬 모델을 찾지 못했습니다 ({_DEFAULT_LOCAL}).\n"
        "HuggingFace Hub 에서 다운로드를 시도합니다 — 사내망에서는 실패할 수 있습니다.\n"
        "로컬 준비 방법:\n"
        "  huggingface-cli download BAAI/bge-m3 "
        f"--local-dir {_DEFAULT_LOCAL} --local-dir-use-symlinks False",
        stacklevel=3,
    )
    return _HUB_ID


def _is_model_complete(model_dir: Path) -> bool:
    """모델 디렉토리에 최소 필수 파일이 있는지 확인."""
    required = ["config.json", "tokenizer_config.json"]
    # safetensors 또는 pytorch_model.bin 중 하나라도 있으면 OK
    weight_exists = any(
        list(model_dir.glob("*.safetensors")) + list(model_dir.glob("pytorch_model*.bin"))
    )
    return all((model_dir / f).exists() for f in required) and weight_exists
