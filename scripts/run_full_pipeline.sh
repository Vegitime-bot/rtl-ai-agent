#!/bin/bash
set -euo pipefail

MODEL_CONFIG=${MODEL_CONFIG:-models/config.yaml}
OUTPUT_V=${OUTPUT_V:-outputs/new.v}
RTL_JSON=${RTL_JSON:-build/rtl_ast.json}
GRAPH_JSON=${GRAPH_JSON:-build/causal_graph.json}
PSEUDO_JSON=${PSEUDO_JSON:-build/pseudo_diff.json}
UARCH_ORIGIN_JSON=${UARCH_ORIGIN_JSON:-build/uarch_origin.json}
UARCH_NEW_JSON=${UARCH_NEW_JSON:-build/uarch_new.json}
FAISS_INDEX=${FAISS_INDEX:-build/faiss_index}
EMBED_MODEL=${EMBED_MODEL:-BAAI/bge-m3}
NEO4J_CONFIG=${NEO4J_CONFIG:-config/neo4j.yaml}
RTL_CHUNKS_JSON=${RTL_CHUNKS_JSON:-build/rtl_chunks.json}

# 1. RTL 파싱
python3 scripts/run_surelog.py inputs/origin.v
python3 scripts/uhdm_extract.py build/origin.uhdm.json --output "$RTL_JSON"

# 2. 그래프 + diff 빌드
python3 scripts/build_graph.py "$RTL_JSON" "$GRAPH_JSON"
python3 scripts/diff_pseudo.py inputs/algorithm_origin.py inputs/algorithm_new.py "$PSEUDO_JSON"

# 3. uArch 청크화
python3 scripts/chunk_ma.py inputs/uArch_origin.txt "$UARCH_ORIGIN_JSON"
python3 scripts/chunk_ma.py inputs/uArch_new.txt "$UARCH_NEW_JSON"

# 4. RTL 청크화 (긴 RTL 대응)
python3 scripts/chunk_rtl.py inputs/origin.v "$RTL_CHUNKS_JSON"

# 5. FAISS 인덱스 빌드 (BGE-M3 시맨틱 RAG)
python3 rag/ingest_faiss.py \
  --index-dir "$FAISS_INDEX" \
  --model-dir "$EMBED_MODEL" \
  "$UARCH_ORIGIN_JSON" "$UARCH_NEW_JSON" \
  inputs/algorithm_origin.py inputs/algorithm_new.py

# 6. Neo4j 그래프 동기화 (선택)
if [ -f "$NEO4J_CONFIG" ]; then
  echo "[run_full_pipeline] syncing Neo4j graph"
  python3 scripts/neo4j_ingest.py --config "$NEO4J_CONFIG"
else
  echo "[run_full_pipeline] skip Neo4j ingest (config not found: $NEO4J_CONFIG)"
fi

# 7. 오케스트레이션 + RTL 생성
python3 orchestrator/flow.py \
  --ip demo \
  --faiss-index "$FAISS_INDEX" \
  --embed-model "$EMBED_MODEL" \
  --model-config "$MODEL_CONFIG" \
  --generate-rtl \
  --output-rtl "$OUTPUT_V"
