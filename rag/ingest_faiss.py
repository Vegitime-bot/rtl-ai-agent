#!/usr/bin/env python3
"""
rag/ingest_faiss.py
────────────────────
uArch / algorithm / RTL 문서 청크를 BGE-M3로 임베딩하고
FAISS 인덱스에 저장한다.

저장 파일 (--index-dir 내):
  chunks.json   — 청크 원문 + 메타데이터
  index.faiss   — FAISS FlatIP 인덱스 (inner product = cosine, 벡터 정규화 전제)

사용:
  python rag/ingest_faiss.py \\
      --index-dir build/faiss_index \\
      --model-dir /path/to/bge-m3        # 오프라인 모델 경로 (없으면 HuggingFace 캐시)
      build/uarch_origin.json build/uarch_new.json \\
      inputs/algorithm_origin.py inputs/algorithm_new.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np


# ── 청크 로더 ────────────────────────────────────

def _load_chunks_from_json(path: Path) -> list[dict]:
    """uarch_*.json (chunk_ma.py 출력) → 청크 리스트."""
    data = json.loads(path.read_text())
    chunks = []
    if "sections" in data:
        for sec in data["sections"]:
            body = sec.get("body", "")
            ref = sec.get("section", "")
            # 섹션이 너무 크면 재분할
            chunks.extend(_split_by_chars(body, str(path), ref, "uarch"))
    elif "diff" in data:
        diff_text = "\n".join(data.get("diff", []))
        chunks.extend(_split_by_chars(diff_text, str(path), data.get("new", ""), "pseudo_diff"))
    elif "modules" in data:
        for mod in data["modules"]:
            mod_text = json.dumps(mod)
            chunks.extend(_split_by_chars(mod_text, str(path), mod.get("module", ""), "rtl"))
    return chunks


_MAX_CHUNK_CHARS = 8000  # ~2000 토큰 상한 (4자 ≈ 1토큰)


def _split_by_chars(text: str, source: str, ref_prefix: str, kind: str) -> list[dict]:
    """텍스트를 _MAX_CHUNK_CHARS 단위로 분할해 청크 리스트 반환."""
    if len(text) <= _MAX_CHUNK_CHARS:
        return [{"kind": kind, "source": source, "ref": ref_prefix, "text": text}]
    chunks = []
    for i, start in enumerate(range(0, len(text), _MAX_CHUNK_CHARS)):
        chunks.append({
            "kind": kind,
            "source": source,
            "ref": f"{ref_prefix}_part{i}",
            "text": text[start:start + _MAX_CHUNK_CHARS],
        })
    return chunks


def _load_chunks_from_py(path: Path) -> list[dict]:
    """Python 파일 → 함수/클래스 단위 청크. 청크가 크면 재분할."""
    source = path.read_text()
    chunks = []
    import re
    # def / class 단위로 분할
    fn_pattern = re.compile(r'^((?:def|class) \w+.*?)(?=^(?:def|class) |\Z)', re.M | re.S)
    for m in fn_pattern.finditer(source):
        fn_text = m.group(1).strip()
        fn_name_m = re.match(r'(?:def|class) (\w+)', fn_text)
        fn_name = fn_name_m.group(1) if fn_name_m else "unknown"
        chunks.extend(_split_by_chars(fn_text, str(path), fn_name, "algorithm"))
    if not chunks:
        # def/class 없으면 전체를 크기 단위로 분할
        chunks.extend(_split_by_chars(source, str(path), path.stem, "algorithm"))
    return chunks


def load_chunks(path: Path) -> list[dict]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return _load_chunks_from_json(path)
    elif suffix in (".py", ".v", ".sv"):
        if suffix == ".py":
            return _load_chunks_from_py(path)
        else:
            return [{"kind": "rtl_raw", "source": str(path), "ref": path.stem, "text": path.read_text()}]
    else:
        return [{"kind": "raw", "source": str(path), "ref": path.stem, "text": path.read_text()}]


# ── 메인 ────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest docs into FAISS index via BGE-M3")
    parser.add_argument("inputs", nargs="+", type=Path, help="JSON / .py / .v files to ingest")
    parser.add_argument("--index-dir", type=Path, default=Path("build/faiss_index"))
    parser.add_argument("--model-dir", type=str, default=None,
                        help="BGE-M3 모델 경로 (생략 시 models/bge-m3/ 자동 사용)")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--max-length", type=int, default=512)
    args = parser.parse_args()

    # 청크 수집
    all_chunks: list[dict] = []
    for path in args.inputs:
        if not path.exists():
            print(f"[ingest_faiss] WARN: {path} not found, skipping")
            continue
        chunks = load_chunks(path)
        print(f"[ingest_faiss] {path.name}: {len(chunks)} chunk(s)")
        all_chunks.extend(chunks)

    if not all_chunks:
        print("[ingest_faiss] No chunks loaded. Exiting.")
        sys.exit(1)

    texts = [c["text"] for c in all_chunks]
    print(f"[ingest_faiss] total chunks: {len(texts)}")

    # 임베딩
    print(f"[ingest_faiss] embedding with {args.model_dir} ...")
    from embed import embed  # type: ignore
    vecs = embed(texts, model_name_or_path=args.model_dir,
                 batch_size=args.batch_size, max_length=args.max_length)
    print(f"[ingest_faiss] vectors: {vecs.shape}")

    # FAISS 인덱스 저장
    try:
        import faiss  # type: ignore
    except ImportError:
        print("[ingest_faiss] ERROR: faiss not installed. Run: pip install faiss-cpu")
        sys.exit(1)

    dim = vecs.shape[1]
    index = faiss.IndexFlatIP(dim)   # Inner Product = cosine (정규화된 벡터 전제)
    index.add(vecs)

    args.index_dir.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(args.index_dir / "index.faiss"))

    # 청크 메타데이터 저장 (벡터 순서와 동일)
    (args.index_dir / "chunks.json").write_text(
        json.dumps(all_chunks, indent=2, ensure_ascii=False)
    )

    print(f"[ingest_faiss] saved {len(all_chunks)} chunks → {args.index_dir}")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    main()
