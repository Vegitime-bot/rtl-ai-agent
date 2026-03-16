#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

DB_PATH="${1:-build/rag.db}"
shift || true

mkdir -p build outputs

echo "[demo] Generating structured RTL"
python3 scripts/parse_rtl.py inputs build/rtl_ast.json

echo "[demo] Diffing pseudo code"
python3 scripts/diff_pseudo.py inputs/algorithm_origin.py inputs/algorithm_new.py build/pseudo_diff.json

echo "[demo] Chunking uArch docs"
python3 scripts/chunk_ma.py inputs/uArch_origin.txt build/uarch_origin.json
python3 scripts/chunk_ma.py inputs/uArch_new.txt build/uarch_new.json

echo "[demo] Building causal graph"
python3 scripts/build_graph.py build/rtl_ast.json build/causal_graph.json

echo "[demo] Ingesting into RAG DB ($DB_PATH)"
python3 rag/ingest.py --db "$DB_PATH" \
  build/rtl_ast.json build/pseudo_diff.json \
  build/uarch_origin.json build/uarch_new.json \
  build/causal_graph.json

echo "[demo] Running orchestrator"
python3 orchestrator/flow.py --ip demo --db "$DB_PATH" "$@"

echo "[demo] Done. See outputs/analysis.md (and bundle artifacts)."
