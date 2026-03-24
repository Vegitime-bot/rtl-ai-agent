# 폐쇄망(사내망) 설치 가이드

Python 패키지(faiss 포함)와 Surelog 바이너리를 인터넷 없이 설치하는 방법.

---

## 1. Python 패키지 (faiss-cpu 포함)

### 1-A. 인터넷 PC에서 wheel 다운로드

```bash
# Linux x86_64 서버용 (기본)
bash scripts/download_wheels.sh

# ARM64 서버용
bash scripts/download_wheels.sh --platform aarch64

# macOS 개발 PC용
bash scripts/download_wheels.sh --platform macos
```

`offline_wheels/` 에 `.whl` 파일이 생성된다.

### 1-B. 사내망 서버로 파일 복사

```
offline_wheels/          ← 전체 디렉토리
requirements.txt
```

### 1-C. 사내망 서버에서 설치

```bash
pip install --no-index --find-links offline_wheels/ -r requirements.txt
```

> ⚠️ **faiss-cpu** 는 Rust/C++ 빌드 없이 설치되는 manylinux wheel 이므로
>    별도 컴파일 불필요. `offline_wheels/` 에 자동 포함된다.

---

## 2. Surelog 바이너리

Surelog 는 C++ 바이너리이므로 pip 로 설치할 수 없다.
아래 세 가지 방법 중 하나를 선택한다.

---

### 방법 A — GitHub Releases 에서 사전 빌드 바이너리 다운로드 (권장)

1. **인터넷 PC** 에서 릴리즈 페이지 접속:
   `https://github.com/chipsalliance/Surelog/releases`

2. 서버 OS에 맞는 바이너리 다운로드:
   - Linux x86_64: `surelog-linux-x86_64.tar.gz` (또는 `.zip`)
   - 공식 릴리즈에 포함된 파일: `surelog`, `uhdm-dump`, `UHDM.capnp`

3. 서버에 복사 후 설치:
   ```bash
   tar -xzf surelog-linux-x86_64.tar.gz
   sudo cp surelog /usr/local/bin/surelog
   sudo chmod +x /usr/local/bin/surelog

   # UHDM 스키마 파일 배치
   sudo mkdir -p /opt/surelog/share/uhdm
   sudo cp UHDM.capnp /opt/surelog/share/uhdm/UHDM.capnp
   ```

4. `run_surelog.py` 에서 스키마 경로 지정:
   ```bash
   python scripts/run_surelog.py inputs/origin.v \
       --schema /opt/surelog/share/uhdm/UHDM.capnp
   ```

---

### 방법 B — Docker 이미지 tar 로 전달

인터넷 PC에서:
```bash
docker pull fvutils/surelog:latest
docker save fvutils/surelog:latest -o surelog_image.tar
```

사내망 서버에서:
```bash
docker load -i surelog_image.tar

# 실행 래퍼 (바이너리처럼 사용 가능)
cat > /usr/local/bin/surelog << 'EOF'
#!/bin/bash
docker run --rm -v "$PWD:/workspace" -w /workspace \
    fvutils/surelog:latest surelog "$@"
EOF
chmod +x /usr/local/bin/surelog
```

---

### 방법 C — 소스 빌드 (인터넷 PC에서 빌드 후 복사)

```bash
# 인터넷 PC (Ubuntu 22.04 권장)
sudo apt-get install -y build-essential cmake git python3 swig \
    libboost-all-dev uuid-dev

git clone --recurse-submodules https://github.com/chipsalliance/Surelog.git
cd Surelog
cmake -DCMAKE_BUILD_TYPE=Release -S . -B build
cmake --build build -j$(nproc)

# 빌드 결과
ls build/bin/surelog
ls build/share/uhdm/UHDM.capnp
```

빌드된 파일을 사내망 서버로 복사.

---

## 3. capnp 설치 (UHDM JSON 변환용)

`run_surelog.py` 의 `convert_uhdm_to_json()` 은 `capnp` CLI 가 필요하다.

```bash
# 인터넷 PC에서 바이너리 다운로드
# Ubuntu:
apt-get download capnproto

# 서버에 복사 후:
sudo dpkg -i capnproto_*.deb
```

또는 GitHub Releases:
`https://github.com/capnproto/capnproto/releases`

---

## 4. 최종 동작 확인

```bash
# Python 패키지
python -c "import faiss; print('faiss OK')"
python -c "from FlagEmbedding import BGEM3FlagModel; print('FlagEmbedding OK')"

# Surelog
surelog --version

# BGE-M3 모델 (로컬 경로 자동 인식)
python -c "
from rag.embed import embed
import numpy as np
v = embed(['test'])
print('embed OK, shape:', v.shape)
"
```
