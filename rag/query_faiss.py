"""
rag/query_faiss.py
───────────────────
FAISS 인덱스에서 시맨틱 검색.

주요 함수:
  load_index(index_dir)          → (faiss_index, chunks)
  search(query, index_dir, ...)  → list[dict]   # 유사 청크 반환

반환 청크 형식:
  {
    "kind":   "uarch" | "algorithm" | ...,
    "source": "...",
    "ref":    "...",
    "text":   "...",
    "score":  0.87,   # cosine similarity
  }
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

_index_cache: dict[str, tuple] = {}   # index_dir → (faiss_index, chunks)


def load_index(index_dir: Path) -> tuple:
    """FAISS 인덱스와 청크 메타데이터를 로드 (캐싱)."""
    key = str(index_dir)
    if key in _index_cache:
        return _index_cache[key]

    try:
        import faiss  # type: ignore
    except ImportError as e:
        raise ImportError("faiss not installed. Run: pip install faiss-cpu") from e

    index_path  = index_dir / "index.faiss"
    chunks_path = index_dir / "chunks.json"

    if not index_path.exists() or not chunks_path.exists():
        raise FileNotFoundError(
            f"FAISS index not found at {index_dir}. "
            "Run rag/ingest_faiss.py first."
        )

    index  = faiss.read_index(str(index_path))
    chunks = json.loads(chunks_path.read_text())
    _index_cache[key] = (index, chunks)
    return index, chunks


def search(
    query: str,
    index_dir: Path = Path("build/faiss_index"),
    top_k: int = 5,
    model_name_or_path: str = "BAAI/bge-m3",
    kind_filter: list[str] | None = None,
    score_threshold: float = 0.0,
) -> list[dict]:
    """
    query와 가장 유사한 청크를 반환.

    Args:
        query:              검색 쿼리 텍스트
        index_dir:          FAISS 인덱스 디렉토리
        top_k:              상위 K개 반환
        model_name_or_path: BGE-M3 모델 경로
        kind_filter:        특정 kind만 필터 (예: ["uarch", "algorithm"])
        score_threshold:    최소 similarity 점수 (0~1)

    반환: score 내림차순 청크 리스트 (score 필드 추가)
    """
    rag_dir = Path(__file__).parent
    if str(rag_dir) not in sys.path:
        sys.path.insert(0, str(rag_dir))

    from embed import embed  # type: ignore

    index, chunks = load_index(index_dir)

    query_vec = embed([query], model_name_or_path=model_name_or_path)  # (1, dim)

    # kind 필터 적용 시 해당 인덱스만 검색
    if kind_filter:
        filtered_idx = [i for i, c in enumerate(chunks) if c.get("kind") in kind_filter]
        if not filtered_idx:
            return []
        # 필터된 벡터만 임시 인덱스 생성
        import faiss
        all_vecs = index.reconstruct_n(0, index.ntotal)
        sub_vecs = all_vecs[filtered_idx]
        sub_index = faiss.IndexFlatIP(sub_vecs.shape[1])
        sub_index.add(sub_vecs)
        scores, local_ids = sub_index.search(query_vec, min(top_k, len(filtered_idx)))
        # local_ids → original chunk idx
        hit_ids   = [filtered_idx[i] for i in local_ids[0] if i >= 0]
        hit_scores = scores[0][:len(hit_ids)]
    else:
        scores, ids = index.search(query_vec, min(top_k, index.ntotal))
        hit_ids    = [i for i in ids[0] if i >= 0]
        hit_scores = scores[0][:len(hit_ids)]

    results = []
    for chunk_id, score in zip(hit_ids, hit_scores):
        if float(score) < score_threshold:
            continue
        chunk = dict(chunks[chunk_id])
        chunk["score"] = round(float(score), 4)
        results.append(chunk)

    return sorted(results, key=lambda x: -x["score"])


def format_search_results(results: list[dict], max_chars: int = 800) -> str:
    """검색 결과를 LLM 프롬프트 주입용 텍스트로 포맷."""
    if not results:
        return "(no relevant context found)"
    lines = []
    for r in results:
        header = f"[{r['kind']}] {r['ref']} (score={r['score']:.2f})"
        body = r["text"][:max_chars] + ("..." if len(r["text"]) > max_chars else "")
        lines.append(f"{header}\n{body}")
    return "\n\n".join(lines)


# CLI
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--index-dir", type=Path, default=Path("build/faiss_index"))
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--kind", nargs="*", help="Filter by kind (uarch, algorithm, ...)")
    parser.add_argument("--model-dir", type=str, default="BAAI/bge-m3")
    args = parser.parse_args()

    hits = search(
        args.query,
        index_dir=args.index_dir,
        top_k=args.top_k,
        model_name_or_path=args.model_dir,
        kind_filter=args.kind,
    )
    print(format_search_results(hits))
