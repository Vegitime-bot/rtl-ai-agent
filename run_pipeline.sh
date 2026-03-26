#!/usr/bin/env bash
# run_pipeline.sh — RTL AI Agent Full Pipeline
# 사용법: ./run_pipeline.sh [추가 flow.py 옵션]
# 예시:   ./run_pipeline.sh
#          ./run_pipeline.sh --no-patch-mode

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ── 가상환경 자동 활성화 ────────────────────────
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
elif [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  RTL AI Agent Pipeline  $(date '+%Y-%m-%d %H:%M:%S')"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── [1] RTL 파싱 ────────────────────────────────
echo "[1/5] RTL 파싱..."
python scripts/parse_rtl.py inputs/rtl build/rtl_ast.json

# ── [2] 인과관계 그래프 빌드 ────────────────────
echo "[2/5] 인과관계 그래프 빌드..."
python scripts/build_graph.py build/rtl_ast.json build/causal_graph.json

# ── [3] RTL 청크 분할 ───────────────────────────
echo "[3/5] RTL 청크 분할..."
# chunk_rtl.py는 RTL 디렉토리 또는 단일 파일을 받음
RTL_INPUT="inputs/rtl"
if [ -d "$RTL_INPUT" ]; then
    # 디렉토리면 첫 번째 .v 파일 사용 (대표 파일)
    FIRST_V=$(ls "$RTL_INPUT"/*.v 2>/dev/null | head -1)
    if [ -n "$FIRST_V" ]; then
        python scripts/chunk_rtl.py "$FIRST_V" build/rtl_chunks.json
    else
        echo "  [skip] .v 파일 없음"
    fi
else
    python scripts/chunk_rtl.py "$RTL_INPUT" build/rtl_chunks.json
fi

# ── [4] Pseudo-diff 생성 ────────────────────────
echo "[4/5] Pseudo-diff 생성..."
python scripts/diff_pseudo.py \
    inputs/algorithm/origin \
    inputs/algorithm/new \
    build/pseudo_diff.json

# ── [5] FAISS 인덱스 빌드 ───────────────────────
echo "[5/5] FAISS 인덱스 빌드..."
INGEST_FILES=""
for f in inputs/algorithm/origin/*.py inputs/algorithm/new/*.py; do
    [ -f "$f" ] && INGEST_FILES="$INGEST_FILES $f"
done
if [ -n "$INGEST_FILES" ]; then
    python rag/ingest_faiss.py --index-dir build/faiss_index $INGEST_FILES
else
    echo "  [skip] algorithm 파일 없음"
fi

# ── [optional] Neo4j 인제스트 ───────────────────
if python -c "from neo4j import GraphDatabase" 2>/dev/null; then
    echo "[optional] Neo4j 인제스트..."
    python scripts/neo4j_ingest.py build/causal_graph.json --clear || echo "  [skip] Neo4j 연결 실패"
fi

# ── RTL 생성 ────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  RTL 생성 시작"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
python orchestrator/flow.py \
    --generate-rtl \
    --model-config models/glm.yaml \
    "$@"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  완료! 결과: outputs/new.v"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
