#!/bin/bash
set -euo pipefail

MODEL_CONFIG=${MODEL_CONFIG:-models/config.yaml}
OUTPUT_V=${OUTPUT_V:-outputs/new.v}
RTL_DIR=${RTL_DIR:-inputs/rtl}           # *.v / *.sv 다중 파일 디렉토리
RTL_JSON=${RTL_JSON:-build/rtl_ast.json}
GRAPH_JSON=${GRAPH_JSON:-build/causal_graph.json}
PSEUDO_JSON=${PSEUDO_JSON:-build/pseudo_diff.json}
UARCH_ORIGIN_JSON=${UARCH_ORIGIN_JSON:-build/uarch_origin.json}
UARCH_NEW_JSON=${UARCH_NEW_JSON:-build/uarch_new.json}
ALGO_ORIGIN_DIR=${ALGO_ORIGIN_DIR:-inputs/algorithm/origin}   # 다중 파일 디렉토리
ALGO_NEW_DIR=${ALGO_NEW_DIR:-inputs/algorithm/new}
FAISS_INDEX=${FAISS_INDEX:-build/faiss_index}
EMBED_MODEL=${EMBED_MODEL:-}   # 생략 시 model_paths.py 가 models/bge-m3/ 자동 사용
NEO4J_CONFIG=${NEO4J_CONFIG:-config/neo4j.yaml}
RTL_CHUNKS_JSON=${RTL_CHUNKS_JSON:-build/rtl_chunks.json}

mkdir -p build outputs

# 1. RTL 파싱 (inputs/rtl/ 내 *.v/*.sv 전체)
python3 scripts/run_surelog.py "$RTL_DIR"
python3 scripts/uhdm_extract.py build/origin.uhdm.json --output "$RTL_JSON"

# 2. 그래프 + diff 빌드
python3 scripts/build_graph.py "$RTL_JSON" "$GRAPH_JSON"

# algorithm diff — origin/ 과 new/ 디렉토리 내 *.py/*.txt 다중 파일 지원
python3 scripts/diff_pseudo.py "$ALGO_ORIGIN_DIR" "$ALGO_NEW_DIR" "$PSEUDO_JSON"

# 3. uArch 청크화 (파일 없으면 스킵)
UARCH_ORIGIN=${UARCH_ORIGIN:-inputs/uArch_origin.txt}
UARCH_NEW=${UARCH_NEW:-inputs/uArch_new.txt}
if [ -f "$UARCH_ORIGIN" ]; then
  python3 scripts/chunk_ma.py "$UARCH_ORIGIN" "$UARCH_ORIGIN_JSON"
else
  echo "[run_full_pipeline] skip uArch origin (not found: $UARCH_ORIGIN)"
fi
if [ -f "$UARCH_NEW" ]; then
  python3 scripts/chunk_ma.py "$UARCH_NEW" "$UARCH_NEW_JSON"
else
  echo "[run_full_pipeline] skip uArch new (not found: $UARCH_NEW)"
fi

# 4. RTL 청크화 (inputs/rtl/ 내 전체 파일)
python3 scripts/chunk_rtl.py "$RTL_DIR" "$RTL_CHUNKS_JSON"

# 5. FAISS 인덱스 빌드 (BGE-M3 시맨틱 RAG)
# EMBED_MODEL 이 비어있으면 --model-dir 생략 → model_paths.py 가 models/bge-m3/ 자동 사용
INGEST_MODEL_ARG=()
[[ -n "$EMBED_MODEL" ]] && INGEST_MODEL_ARG=(--model-dir "$EMBED_MODEL")

# algorithm 파일 목록 수집 (origin/ + new/ 디렉토리 전체)
ALGO_FILES=()
for f in "$ALGO_ORIGIN_DIR"/*.py "$ALGO_ORIGIN_DIR"/*.txt \
         "$ALGO_NEW_DIR"/*.py    "$ALGO_NEW_DIR"/*.txt; do
  [[ -f "$f" ]] && ALGO_FILES+=("$f")
done

# uArch JSON 존재하는 것만 수집
UARCH_INGEST_FILES=()
[ -f "$UARCH_ORIGIN_JSON" ] && UARCH_INGEST_FILES+=("$UARCH_ORIGIN_JSON")
[ -f "$UARCH_NEW_JSON"    ] && UARCH_INGEST_FILES+=("$UARCH_NEW_JSON")

python3 rag/ingest_faiss.py \
  --index-dir "$FAISS_INDEX" \
  "${INGEST_MODEL_ARG[@]}" \
  "${UARCH_INGEST_FILES[@]}" \
  "${ALGO_FILES[@]}"

# 6. Neo4j 그래프 동기화 (선택)
if [ -f "$NEO4J_CONFIG" ]; then
  echo "[run_full_pipeline] syncing Neo4j graph"
  python3 scripts/neo4j_ingest.py --config "$NEO4J_CONFIG"
else
  echo "[run_full_pipeline] skip Neo4j ingest (config not found: $NEO4J_CONFIG)"
fi

# 7. 오케스트레이션 + RTL 생성
FLOW_MODEL_ARG=()
[[ -n "$EMBED_MODEL" ]] && FLOW_MODEL_ARG=(--embed-model "$EMBED_MODEL")

python3 orchestrator/flow.py \
  --ip demo \
  --origin-rtl-dir  "$RTL_DIR" \
  --faiss-index     "$FAISS_INDEX" \
  "${FLOW_MODEL_ARG[@]}" \
  --algo-origin-dir "$ALGO_ORIGIN_DIR" \
  --algo-new-dir    "$ALGO_NEW_DIR" \
  --model-config    "$MODEL_CONFIG" \
  --generate-rtl \
  --output-rtl      "$OUTPUT_V"
