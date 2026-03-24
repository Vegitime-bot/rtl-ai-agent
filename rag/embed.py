"""
rag/embed.py
─────────────
BGE-M3 임베딩 헬퍼.

FlagEmbedding(BAAI/bge-m3)을 로컬에서 로드하고
텍스트 리스트 → dense 벡터(numpy) 를 반환한다.

모델 경로 해석 순서 (model_paths.py):
  1. 환경변수 RTL_BGE_MODEL_DIR
  2. 프로젝트 내부  models/bge-m3/
  3. HuggingFace Hub 폴백 (사내망에선 사용 불가)

의존: FlagEmbedding==1.2.11, tokenizers==0.19.1, transformers==4.40.2
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

# model_paths 가 같은 디렉토리에 있으므로 경로 보장
_RAG_DIR = Path(__file__).resolve().parent
if str(_RAG_DIR) not in sys.path:
    sys.path.insert(0, str(_RAG_DIR))

from model_paths import resolve_bge_model_path  # type: ignore

_model = None
_model_path: str | None = None


def _load_model(model_name_or_path: str | None = None) -> object:
    global _model, _model_path

    resolved = model_name_or_path or resolve_bge_model_path()

    if _model is not None and _model_path == resolved:
        return _model

    try:
        from FlagEmbedding import BGEM3FlagModel  # type: ignore
    except ImportError as e:
        raise ImportError(
            "FlagEmbedding 이 설치되지 않았습니다.\n"
            "  pip install FlagEmbedding==1.2.11"
        ) from e

    _model = BGEM3FlagModel(resolved, use_fp16=True)
    _model_path = resolved
    return _model


def embed(
    texts: list[str],
    model_name_or_path: str | None = None,
    batch_size: int = 16,
    max_length: int = 512,
) -> np.ndarray:
    """
    텍스트 리스트를 dense 벡터로 변환.

    Args:
        texts:              임베딩할 텍스트 리스트
        model_name_or_path: 모델 경로. None 이면 model_paths.resolve_bge_model_path() 사용.
        batch_size:         배치 크기
        max_length:         최대 토큰 길이

    반환: shape (N, 1024) float32 ndarray (L2 정규화 완료)
    """
    if not texts:
        return np.empty((0, 1024), dtype=np.float32)

    model = _load_model(model_name_or_path)
    result = model.encode(
        texts,
        batch_size=batch_size,
        max_length=max_length,
        return_dense=True,
        return_sparse=False,
        return_colbert_vecs=False,
    )
    vecs = result["dense_vecs"]
    # L2 정규화 (cosine similarity ≡ inner product)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return (vecs / norms).astype(np.float32)
