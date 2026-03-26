#!/usr/bin/env bash
# init.sh — RTL AI Agent 사전 초기화
# run_pipeline.sh 실행 전에 한 번 실행하세요.
# 사용법: ./init.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  RTL AI Agent Init  $(date '+%Y-%m-%d %H:%M:%S')"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── [1] 가상환경 자동 활성화 ────────────────────
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
    echo "[init] venv 활성화: .venv"
elif [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
    echo "[init] venv 활성화: venv"
else
    echo "[init] ⚠️  venv 없음 — 시스템 Python 사용"
fi

# ── [2] Neo4j 시작 ──────────────────────────────
echo ""
echo "[1/3] Neo4j 시작..."
if command -v neo4j &>/dev/null; then
    STATUS=$(neo4j status 2>/dev/null || echo "not running")
    if echo "$STATUS" | grep -q "running"; then
        echo "  ✅ Neo4j 이미 실행 중"
    else
        neo4j start
        echo "  ⏳ Neo4j 시작 중... (최대 15초 대기)"
        for i in $(seq 1 15); do
            sleep 1
            if neo4j status 2>/dev/null | grep -q "running"; then
                echo "  ✅ Neo4j 시작 완료 (${i}초)"
                break
            fi
        done
    fi
elif command -v brew &>/dev/null && brew services list 2>/dev/null | grep -q neo4j; then
    STATUS=$(brew services list | grep neo4j | awk '{print $2}')
    if [ "$STATUS" = "started" ]; then
        echo "  ✅ Neo4j 이미 실행 중 (brew)"
    else
        brew services start neo4j
        echo "  ⏳ Neo4j 시작 중... (최대 15초 대기)"
        sleep 5
        echo "  ✅ Neo4j 시작 요청 완료 (brew)"
    fi
else
    echo "  ⚠️  Neo4j CLI 없음 — 수동으로 시작하거나 Docker 사용"
    echo "  힌트: docker run -p 7687:7687 -e NEO4J_AUTH=neo4j/\$NEO4J_PASSWORD neo4j"
fi

# ── [3] ai-verilog-lsp 서버 시작 ────────────────
echo ""
echo "[2/3] LSP 서버 시작..."
LSP_DIR="$SCRIPT_DIR/../ai-verilog-lsp"
LSP_PORT=7342

if [ ! -d "$LSP_DIR" ]; then
    echo "  ⚠️  ai-verilog-lsp 디렉토리 없음 (skip): $LSP_DIR"
else
    # 이미 포트 사용 중인지 확인
    if lsof -i :$LSP_PORT &>/dev/null 2>&1; then
        echo "  ✅ LSP 서버 이미 실행 중 (port $LSP_PORT)"
    else
        echo "  LSP 서버 백그라운드 시작 (port $LSP_PORT)..."
        cd "$LSP_DIR"
        TRANSPORT=http nohup npm run dev --workspace @ai-verilog-lsp/server \
            > "$SCRIPT_DIR/logs/lsp.log" 2>&1 &
        LSP_PID=$!
        echo $LSP_PID > "$SCRIPT_DIR/logs/lsp.pid"
        cd "$SCRIPT_DIR"

        # 포트 올라올 때까지 대기 (최대 15초)
        for i in $(seq 1 15); do
            sleep 1
            if lsof -i :$LSP_PORT &>/dev/null 2>&1; then
                echo "  ✅ LSP 서버 시작 완료 (${i}초, pid=$LSP_PID)"
                break
            fi
            if [ $i -eq 15 ]; then
                echo "  ⚠️  LSP 서버 시작 timeout — logs/lsp.log 확인"
            fi
        done
    fi
fi

# ── [4] 연결 상태 최종 확인 ─────────────────────
echo ""
echo "[3/3] 연결 상태 확인..."

# Neo4j
if python3 -c "
from neo4j import GraphDatabase
import os
pw = os.environ.get('NEO4J_PASSWORD', '')
if not pw:
    print('  ⚠️  NEO4J_PASSWORD 환경변수 없음')
    exit(0)
try:
    d = GraphDatabase.driver('bolt://127.0.0.1:7687', auth=('neo4j', pw))
    d.verify_connectivity()
    d.close()
    print('  ✅ Neo4j 연결 OK')
except Exception as e:
    print(f'  ❌ Neo4j 연결 실패: {e}')
" 2>/dev/null; then : ; fi

# LSP
if curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:$LSP_PORT/spec-summary \
    -X POST -H "Content-Type: application/json" \
    -d '{"uri":"file:///dev/null"}' 2>/dev/null | grep -qE "^[24]"; then
    echo "  ✅ LSP 서버 응답 OK (port $LSP_PORT)"
else
    echo "  ⚠️  LSP 서버 응답 없음 (port $LSP_PORT) — run_pipeline은 skip하고 계속 진행"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Init 완료! 이제 ./run_pipeline.sh 를 실행하세요."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
