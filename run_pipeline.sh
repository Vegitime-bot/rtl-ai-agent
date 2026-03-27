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
python3 scripts/parse_rtl.py inputs/rtl build/rtl_ast.json

# ── [2] 인과관계 그래프 빌드 ────────────────────
echo "[2/5] 인과관계 그래프 빌드..."
python3 scripts/build_graph.py build/rtl_ast.json build/causal_graph.json

# ── [3] RTL 청크 분할 ───────────────────────────
echo "[3/5] RTL 청크 분할 (파일별, flow.py 내부에서 처리)..."
# 파일별 청크 생성은 flow.py 루프 내에서 각 .v 파일마다 수행
echo "  [skip] flow.py에서 파일별 자동 생성"

# ── [4] Pseudo-diff 생성 ────────────────────────
echo "[4/5] Pseudo-diff 생성..."
python3 scripts/diff_pseudo.py \
    inputs/algorithm/origin \
    inputs/algorithm/new \
    build/pseudo_diff.json

# ── [5] FAISS 인덱스 빌드 ───────────────────────
echo "[5/5] FAISS 인덱스 빌드..."
INGEST_FILES=""
# algorithm (py)
for f in inputs/algorithm/origin/*.py inputs/algorithm/new/*.py; do
    [ -f "$f" ] && INGEST_FILES="$INGEST_FILES $f"
done
# uArch (txt)
for f in inputs/uArch_origin.txt inputs/uArch_new.txt; do
    [ -f "$f" ] && INGEST_FILES="$INGEST_FILES $f"
done
if [ -n "$INGEST_FILES" ]; then
    python3 rag/ingest_faiss.py --index-dir build/faiss_index $INGEST_FILES
else
    echo "  [skip] ingest 파일 없음"
fi

# ── [optional] Neo4j 인제스트 ───────────────────
if python3 -c "from neo4j import GraphDatabase" 2>/dev/null; then
    echo "[optional] Neo4j 인제스트..."
    python3 scripts/neo4j_ingest.py --graph-json build/causal_graph.json --config config/neo4j.yaml --clear || echo "  [skip] Neo4j 연결 실패"
fi

# ── RTL 생성 ────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  RTL 생성 시작"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
# --model-config가 "$@"에 없으면 기본값 models/glm.yaml 사용
MODEL_CONFIG="models/glm.yaml"
for arg in "$@"; do
    if [[ "$prev" == "--model-config" ]]; then
        MODEL_CONFIG="$arg"
    fi
    prev="$arg"
done

python3 orchestrator/flow.py \
    --generate-rtl \
    --model-config "$MODEL_CONFIG" \
    --embed-model models/bge-m3 \
    "$@"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  완료! 결과: outputs/new.v"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
