#!/usr/bin/env bash
# run_pipeline.sh — RTL AI Agent Full Pipeline
# 사용법:
#   ./run_pipeline.sh [--patch-mode] [--model-config path/to/model.yaml] [추가 flow.py 옵션]
#
# 예시:
#   ./run_pipeline.sh --patch-mode --model-config config/model.yaml
#   ./run_pipeline.sh --model-config config/model.yaml --max-retries 3

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ── 가상환경 자동 활성화 ─────────────────────────────────────
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
elif [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  RTL AI Agent Pipeline"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── BUILD PHASE ──────────────────────────────────
echo ""
echo "[1/5] RTL 파싱..."
python scripts/parse_rtl.py

echo "[2/5] 인과관계 그래프 빌드..."
python scripts/build_graph.py

echo "[3/5] RTL 청크 분할..."
python scripts/chunk_rtl.py

echo "[4/5] Pseudo-diff 생성..."
python scripts/diff_pseudo.py

echo "[5/5] FAISS 인덱스 빌드..."
ALGO_ORIGIN_FILES=$(ls inputs/algorithm/origin/*.py 2>/dev/null || true)
ALGO_NEW_FILES=$(ls inputs/algorithm/new/*.py 2>/dev/null || true)
if [ -n "$ALGO_ORIGIN_FILES" ] || [ -n "$ALGO_NEW_FILES" ]; then
    python rag/ingest_faiss.py --index-dir build/faiss_index \
        $ALGO_ORIGIN_FILES $ALGO_NEW_FILES
else
    echo "  [skip] algorithm 파일 없음"
fi

# ── Neo4j 인제스트 (선택) ────────────────────────
if [ -f "build/causal_graph.json" ] && command -v neo4j &>/dev/null 2>&1; then
    echo "[optional] Neo4j 인제스트..."
    python scripts/neo4j_ingest.py || echo "  [skip] Neo4j 연결 실패, 무시"
fi

# ── INFERENCE PHASE ──────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  RTL 생성 시작"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
python orchestrator/flow.py --generate-rtl "$@"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  완료! 결과: outputs/new.v"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
