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

> ⚠️ **faiss-cpu** 는 manylinux wheel 이므로 별도 컴파일 불필요.
>    `offline_wheels/` 에 자동 포함된다.

---

## 2. Surelog 바이너리

> ℹ️ Surelog GitHub Releases 에는 **사전 빌드 바이너리가 없다** (소스 tarball만 제공).
> 공식 사전 빌드는 **conda-forge** 를 통해 제공된다.

---

### 방법 A — conda-forge 패키지 오프라인 전달 (권장)

#### 2-A-1. 인터넷 PC에서 conda 패키지 다운로드

```bash
# conda 없으면 먼저 설치
# https://docs.conda.io/en/latest/miniconda.html

# Surelog conda 패키지 + 의존성 다운로드
conda install -c conda-forge surelog --download-only
# 또는 명시적으로 tar 파일만 받기
conda install -c conda-forge surelog --download-only --no-deps \
    --packages-path ./surelog_conda/
```

또는 직접 파일 다운로드:
```bash
# linux-64 패키지 직접 다운로드
curl -L "https://anaconda.org/conda-forge/surelog/1.84/download/linux-64/surelog-1.84-hb0f4dca_0.conda" \
     -o surelog_conda/surelog-1.84-linux-64.conda

# 의존 라이브러리도 함께 받아야 함
conda create -n tmp_env -c conda-forge surelog --download-only
# 패키지 캐시 경로: ~/miniconda3/pkgs/ 또는 ~/anaconda3/pkgs/
```

#### 2-A-2. 사내망 서버에서 설치

```bash
# conda 채널 없이 로컬 패키지로 설치
conda install --use-local surelog_conda/surelog-1.84-linux-64.conda

# 또는 로컬 채널 구성
mkdir -p local_channel/linux-64
cp surelog_conda/*.conda local_channel/linux-64/
conda index local_channel/
conda install -c file:///path/to/local_channel surelog
```

---

### 방법 B — scripts/download_surelog.sh 자동화 스크립트 사용

```bash
# 인터넷 PC에서
bash scripts/download_surelog.sh

# 사내망 서버에서
bash scripts/install_surelog.sh
```

→ 아래 스크립트가 `surelog_pkg/` 디렉토리를 생성하고 바이너리를 추출해 배치한다.

---

### 방법 C — Docker tar (conda 없는 환경)

인터넷 PC에서:
```bash
docker pull condaforge/mambaforge:latest
# 이미지 내에서 설치 후 바이너리 추출
docker run --rm condaforge/mambaforge:latest \
    bash -c "conda install -c conda-forge surelog -y && tar -czf /tmp/surelog.tar.gz \$(which surelog) /opt/conda/lib/libsurelog*" \
    > /dev/null
docker run --rm condaforge/mambaforge:latest \
    bash -c "conda install -c conda-forge surelog -y && which surelog && cat \$(which surelog)" \
    | tar -xz -C surelog_pkg/
```

또는 더 간단하게:
```bash
docker pull condaforge/mambaforge:latest
docker save condaforge/mambaforge:latest -o mambaforge.tar
# → 사내망 서버로 복사 후 docker load -i mambaforge.tar
```

---

### 방법 D — 소스 빌드 (인터넷 PC에서 빌드 후 복사)

```bash
# Ubuntu 22.04 권장
sudo apt-get install -y build-essential cmake git python3 swig \
    libboost-all-dev uuid-dev default-jdk

git clone --recurse-submodules https://github.com/chipsalliance/Surelog.git
cd Surelog
cmake -DCMAKE_BUILD_TYPE=Release -S . -B build
cmake --build build -j$(nproc)

# 정적 링크 바이너리 확인
ldd build/bin/surelog  # 의존 so 파일 최소화 확인
```

빌드된 `build/bin/surelog` 과 `build/share/uhdm/UHDM.capnp` 를 서버에 복사.

---

## 3. capnp CLI (UHDM JSON 변환용)

`run_surelog.py` 의 JSON 변환 기능에 필요. conda로 Surelog 설치 시 자동 포함.

소스 빌드 경우:
```bash
# 인터넷 PC에서 deb 패키지 다운로드
apt-get download capnproto libcapnp-dev
# 사내망 서버에서:
sudo dpkg -i capnproto_*.deb libcapnp-dev_*.deb
```

---

## 4. 최종 동작 확인

```bash
# Python 패키지
python -c "import faiss; print('faiss OK, version:', faiss.__version__)"
python -c "from FlagEmbedding import BGEM3FlagModel; print('FlagEmbedding OK')"

# BGE-M3 로컬 모델 자동 인식
python -c "
import sys; sys.path.insert(0, 'rag')
from embed import embed
v = embed(['test RTL signal'])
print('embed OK, shape:', v.shape)
"

# Surelog
surelog --version
```

---

## 5. 설치 파일 전달 체크리스트

| 항목 | 방법 | 위치 |
|---|---|---|
| Python wheel 전체 | `download_wheels.sh` | `offline_wheels/` |
| BGE-M3 모델 가중치 | `download_bge_m3.py` | `models/bge-m3/pytorch_model.bin` |
| Surelog 바이너리 | conda-forge (방법 A) | `/usr/local/bin/surelog` |
| UHDM.capnp 스키마 | Surelog 설치 시 포함 | `/opt/conda/share/uhdm/UHDM.capnp` |
