#!/usr/bin/env bash
# ============================================================
# scripts/install_surelog.sh
# ============================================================
# 사내망 서버에서 실행.
# surelog_pkg/extracted/ 에서 surelog 바이너리를 시스템에 설치한다.
#
# 사용:
#   bash scripts/install_surelog.sh
#   bash scripts/install_surelog.sh --prefix /opt/surelog   # 커스텀 설치 경로
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PKG_DIR="$PROJECT_ROOT/surelog_pkg/extracted"
PREFIX="/usr/local"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prefix) PREFIX="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

if [[ ! -d "$PKG_DIR" ]]; then
  echo "[install_surelog] ERROR: surelog_pkg/extracted/ 가 없습니다."
  echo "먼저 인터넷 PC에서 scripts/download_surelog.sh 를 실행하세요."
  exit 1
fi

echo "[install_surelog] 설치 경로: $PREFIX"

# 바이너리 설치
SURELOG_BIN=$(find "$PKG_DIR" -name "surelog" -type f 2>/dev/null | head -1)
if [[ -z "$SURELOG_BIN" ]]; then
  echo "[install_surelog] ERROR: surelog 바이너리를 찾을 수 없습니다."
  echo "surelog_pkg/extracted/ 내용:"
  ls "$PKG_DIR"
  exit 1
fi

sudo install -m 755 "$SURELOG_BIN" "$PREFIX/bin/surelog"
echo "[install_surelog] 바이너리: $PREFIX/bin/surelog"

# UHDM.capnp 스키마 설치
UHDM_CAPNP=$(find "$PKG_DIR" -name "UHDM.capnp" -type f 2>/dev/null | head -1)
if [[ -n "$UHDM_CAPNP" ]]; then
  sudo mkdir -p "$PREFIX/share/uhdm"
  sudo install -m 644 "$UHDM_CAPNP" "$PREFIX/share/uhdm/UHDM.capnp"
  echo "[install_surelog] 스키마: $PREFIX/share/uhdm/UHDM.capnp"
fi

# 공유 라이브러리 설치 (있는 경우)
SO_FILES=$(find "$PKG_DIR" -name "*.so*" -type f 2>/dev/null)
if [[ -n "$SO_FILES" ]]; then
  sudo mkdir -p "$PREFIX/lib"
  while IFS= read -r so; do
    sudo install -m 755 "$so" "$PREFIX/lib/"
  done <<< "$SO_FILES"
  sudo ldconfig 2>/dev/null || true
  echo "[install_surelog] 공유 라이브러리 설치 완료"
fi

echo ""
echo "[install_surelog] 설치 완료!"
echo ""
# 동작 확인
if command -v surelog &>/dev/null; then
  echo "확인: $(surelog --version 2>&1 | head -1)"
else
  echo "PATH 에 $PREFIX/bin 이 포함되어 있는지 확인하세요:"
  echo "  export PATH=$PREFIX/bin:\$PATH"
fi

echo ""
echo "run_surelog.py 사용 시 --schema 지정:"
echo "  python scripts/run_surelog.py inputs/origin.v \\"
echo "      --schema $PREFIX/share/uhdm/UHDM.capnp"
