#!/usr/bin/env bash
# ============================================================
# scripts/download_wheels.sh
# ============================================================
# 사내망(폐쇄망) 오프라인 설치를 위해
# 인터넷 환경에서 모든 Python wheel 을 미리 다운로드한다.
#
# 사용:
#   bash scripts/download_wheels.sh              # Linux x86_64 (서버 기본)
#   bash scripts/download_wheels.sh --platform aarch64   # ARM64 서버
#   bash scripts/download_wheels.sh --platform macos     # macOS (개발 PC)
#
# 출력: offline_wheels/ 디렉토리
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
WHEEL_DIR="$PROJECT_ROOT/offline_wheels"

PLATFORM="linux_x86_64"   # 기본: 사내망 Linux 서버
while [[ $# -gt 0 ]]; do
  case "$1" in
    --platform)
      PLATFORM="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

case "$PLATFORM" in
  linux_x86_64|x86_64)
    PY_PLATFORM="manylinux2014_x86_64" ;;
  linux_aarch64|aarch64|arm64_linux)
    PY_PLATFORM="manylinux2014_aarch64" ;;
  macos|darwin|arm64_mac)
    PY_PLATFORM="macosx_11_0_arm64" ;;
  *)
    echo "Unknown platform: $PLATFORM"
    echo "Use: linux_x86_64 | aarch64 | macos"
    exit 1 ;;
esac

echo "[download_wheels] 플랫폼: $PY_PLATFORM"
echo "[download_wheels] 출력 디렉토리: $WHEEL_DIR"
mkdir -p "$WHEEL_DIR"

# PyTorch CPU 는 공식 인덱스에서만 제공 → 별도 다운로드
echo "[download_wheels] torch 2.2.2 (CPU) 다운로드..."
pip download torch==2.2.2 \
    --index-url https://download.pytorch.org/whl/cpu \
    --python-version 311 \
    --platform "$PY_PLATFORM" \
    --no-deps \
    -d "$WHEEL_DIR"

# 나머지 의존성 전체
echo "[download_wheels] 나머지 패키지 다운로드..."
pip download \
    --python-version 311 \
    --platform "$PY_PLATFORM" \
    --only-binary :all: \
    -d "$WHEEL_DIR" \
    requests==2.31.0 \
    PyYAML==6.0.1 \
    pygls==2.0.1 \
    neo4j==5.19.0 \
    numpy==1.26.4 \
    transformers==4.40.2 \
    tokenizers==0.19.1 \
    huggingface_hub==0.23.4 \
    safetensors==0.4.3 \
    "FlagEmbedding==1.2.11" \
    "faiss-cpu==1.7.4"

echo ""
echo "[download_wheels] 완료! 파일 목록:"
ls -lh "$WHEEL_DIR"/*.whl 2>/dev/null | awk '{print $5, $9}'
echo ""
echo "사내망 서버 설치 명령:"
echo "  pip install --no-index --find-links offline_wheels/ -r requirements.txt"
