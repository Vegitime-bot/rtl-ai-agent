#!/bin/bash
set -euo pipefail

MODEL_CONFIG=${MODEL_CONFIG:-models/config.yaml}
DB_PATH=${DB_PATH:-build/rag.db}
OUTPUT_V=${OUTPUT_V:-outputs/new.v}
RTL_JSON=${RTL_JSON:-build/rtl_ast.json}
GRAPH_JSON=${GRAPH_JSON:-build/causal_graph.json}
PSEUDO_JSON=${PSEUDO_JSON:-build/pseudo_diff.json}
UARCH_ORIGIN_JSON=${UARCH_ORIGIN_JSON:-build/uarch_origin.json}
UARCH_NEW_JSON=${UARCH_NEW_JSON:-build/uarch_new.json}
NEO4J_CONFIG=${NEO4J_CONFIG:-config/neo4j.yaml}

python3 scripts/run_surelog.py inputs/origin.v
python3 scripts/uhdm_extract.py build/origin.uhdm.json --output "$RTL_JSON"
python3 scripts/build_graph.py "$RTL_JSON" "$GRAPH_JSON"
python3 scripts/diff_pseudo.py inputs/algorithm_origin.py inputs/algorithm_new.py "$PSEUDO_JSON"
python3 scripts/chunk_ma.py inputs/uArch_origin.txt "$UARCH_ORIGIN_JSON"
python3 scripts/chunk_ma.py inputs/uArch_new.txt "$UARCH_NEW_JSON"
python3 rag/ingest.py --db "$DB_PATH" \
  "$RTL_JSON" "$PSEUDO_JSON" "$UARCH_ORIGIN_JSON" "$UARCH_NEW_JSON" "$GRAPH_JSON"

if [ -f "$NEO4J_CONFIG" ]; then
  echo "[run_full_pipeline] syncing Neo4j graph"
  python3 scripts/neo4j_ingest.py --config "$NEO4J_CONFIG"
else
  echo "[run_full_pipeline] skip Neo4j ingest (config not found: $NEO4J_CONFIG)"
fi

python3 orchestrator/flow.py --ip demo --db "$DB_PATH" \
  --model-config "$MODEL_CONFIG" --generate-rtl --output-rtl "$OUTPUT_V"
