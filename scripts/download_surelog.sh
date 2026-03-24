#!/usr/bin/env bash
# ============================================================
# scripts/download_surelog.sh
# ============================================================
# Surelog 바이너리를 conda-forge에서 다운로드하고
# surelog_pkg/ 디렉토리에 추출한다.
#
# 인터넷이 되는 환경(개발 PC)에서 1회 실행 후
# surelog_pkg/ 를 사내망 서버로 복사하고
# scripts/install_surelog.sh 를 실행한다.
#
# 사용:
#   bash scripts/download_surelog.sh           # linux-64 (기본)
#   bash scripts/download_surelog.sh --version 1.84
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PKG_DIR="$PROJECT_ROOT/surelog_pkg"
VERSION="1.84"
PLATFORM="linux-64"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version) VERSION="$2"; shift 2 ;;
    --platform) PLATFORM="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

mkdir -p "$PKG_DIR"

echo "[download_surelog] Surelog v${VERSION} (${PLATFORM}) 다운로드..."

# ── conda-forge에서 .conda 패키지 직접 다운로드 ──────────────
# 파일명 패턴: surelog-{version}-*_{build}.conda
# repodata에서 정확한 파일명 조회
REPODATA_URL="https://conda.anaconda.org/conda-forge/${PLATFORM}/repodata.json.zst"
REPODATA_BZ2_URL="https://conda.anaconda.org/conda-forge/${PLATFORM}/repodata.json.bz2"

echo "[download_surelog] repodata 에서 패키지명 조회..."
FILENAME=$(python3 - <<PYEOF
import urllib.request, json, bz2, sys

try:
    url = "${REPODATA_BZ2_URL}"
    with urllib.request.urlopen(url, timeout=30) as r:
        data = json.loads(bz2.decompress(r.read()))
    version = "${VERSION}"
    for name, info in data.get("packages.conda", {}).items():
        if info.get("name") == "surelog" and info.get("version") == version:
            print(name)
            sys.exit(0)
    for name, info in data.get("packages", {}).items():
        if info.get("name") == "surelog" and info.get("version") == version:
            print(name)
            sys.exit(0)
    print("NOT_FOUND")
except Exception as e:
    print(f"ERROR: {e}", file=sys.stderr)
    print("NOT_FOUND")
PYEOF
)

if [[ "$FILENAME" == "NOT_FOUND" ]] || [[ "$FILENAME" == ERROR* ]]; then
  echo "[download_surelog] repodata 조회 실패 — 직접 URL로 시도..."
  # fallback: 알려진 빌드 파일명
  FILENAME="surelog-${VERSION}-hb0f4dca_0.conda"
fi

echo "[download_surelog] 파일명: $FILENAME"
BASE_URL="https://conda.anaconda.org/conda-forge/${PLATFORM}/${FILENAME}"
DEST="$PKG_DIR/$FILENAME"

if [[ -f "$DEST" ]]; then
  echo "[download_surelog] 이미 존재: $DEST"
else
  echo "[download_surelog] 다운로드: $BASE_URL"
  curl -L "$BASE_URL" -o "$DEST"
fi

# ── 패키지에서 바이너리 추출 ─────────────────────────────────
echo "[download_surelog] 바이너리 추출..."
python3 - <<PYEOF
import zipfile, pathlib, shutil, sys

pkg_path = pathlib.Path("$DEST")
out_dir  = pathlib.Path("$PKG_DIR")

# .conda 는 zip 포맷
try:
    with zipfile.ZipFile(pkg_path) as zf:
        names = zf.namelist()
        # pkg-{arch}.tar.zst 또는 pkg.tar.bz2 안에 실제 파일
        inner = [n for n in names if n.endswith(".tar.zst") or n.endswith(".tar.bz2")]
        if inner:
            import tempfile, os
            with tempfile.TemporaryDirectory() as tmp:
                zf.extract(inner[0], tmp)
                inner_path = pathlib.Path(tmp) / inner[0]
                # tar 추출
                import tarfile
                if inner[0].endswith(".tar.bz2"):
                    tf = tarfile.open(inner_path, "r:bz2")
                else:
                    # .tar.zst: zstandard 필요
                    try:
                        import zstandard as zstd
                        with open(inner_path, "rb") as f:
                            dctx = zstd.ZstdDecompressor()
                            with dctx.stream_reader(f) as reader:
                                tf = tarfile.open(fileobj=reader)
                                tf.extractall(out_dir / "extracted")
                        tf = None
                    except ImportError:
                        print("[extract] zstandard 없음. pip install zstandard 후 재시도 또는 conda install 방법 사용")
                        sys.exit(0)
                if tf:
                    tf.extractall(out_dir / "extracted")
                    tf.close()
            print(f"[extract] 완료: {out_dir / 'extracted'}")
        else:
            print("[extract] inner tar 없음 — conda install 방법 권장")
except Exception as e:
    print(f"[extract] 오류: {e}")
PYEOF

echo ""
echo "[download_surelog] 완료!"
echo ""
echo "다음 단계:"
echo "  1. surelog_pkg/ 디렉토리를 사내망 서버로 복사"
echo "  2. 사내망 서버에서: bash scripts/install_surelog.sh"
