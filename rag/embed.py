"""
rag/embed.py
─────────────
BGE-M3 임베딩 헬퍼.

FlagEmbedding(BAAI/bge-m3)을 로컬에서 로드하고
텍스트 리스트 → dense 벡터(numpy) 를 반환한다.

의존: FlagEmbedding (pip install FlagEmbedding)
모델: BAAI/bge-m3 (로컬 캐시 또는 --model-dir로 오프라인 경로 지정)
"""
from __future__ import annotations

import warnings
from pathlib import Path
from typing import Union

import numpy as np

_model = None
_model_name: str | None = None


def _load_model(model_name_or_path: str = "BAAI/bge-m3") -> object:
    global _model, _model_name
    if _model is not None and _model_name == model_name_or_path:
        return _model
    try:
        from FlagEmbedding import BGEM3FlagModel  # type: ignore
        _model = BGEM3FlagModel(model_name_or_path, use_fp16=True)
        _model_name = model_name_or_path
        return _model
    except ImportError as e:
        raise ImportError(
            "FlagEmbedding not installed. Run: pip install FlagEmbedding"
        ) from e


def embed(
    texts: list[str],
    model_name_or_path: str = "BAAI/bge-m3",
    batch_size: int = 16,
    max_length: int = 512,
) -> np.ndarray:
    """
    텍스트 리스트를 dense 벡터로 변환.

    반환: shape (N, 1024) float32 ndarray
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
    # normalize (cosine similarity 기반 검색용)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return (vecs / norms).astype(np.float32)
