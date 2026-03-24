# models/bge-m3/

BAAI/bge-m3 모델 파일을 이 디렉토리에 배치한다.

## 준비 방법

### 방법 A — 자동 다운로드 스크립트 (인터넷 가능 PC에서)

```bash
# 프로젝트 루트에서 실행
python scripts/download_bge_m3.py
```

완료 후 이 디렉토리를 사내망 서버에 그대로 복사.

---

### 방법 B — HuggingFace CLI 직접 사용

```bash
pip install huggingface_hub==0.23.4

huggingface-cli download BAAI/bge-m3 \
    --local-dir models/bge-m3 \
    --local-dir-use-symlinks False
```

---

### 방법 C — 환경변수로 외부 경로 지정

모델을 다른 경로에 두고 싶다면:

```bash
export RTL_BGE_MODEL_DIR=/data/shared_models/bge-m3
```

프로세스 기동 전 설정해 두면 models/bge-m3/ 보다 우선 사용.

---

## 필수 파일 목록

아래 파일이 모두 있어야 `model_paths.py` 가 완전한 모델로 인식한다:

```
config.json
tokenizer_config.json
tokenizer.json
special_tokens_map.json
sentencepiece.bpe.model          (또는 tokenizer.model)
model.safetensors  (또는 pytorch_model.bin / pytorch_model-00001-of-xxxxx.bin)
```

> ⚠️  이 디렉토리 자체는 `.gitignore` 에 추가하거나,
>    모델 파일만 제외(`models/bge-m3/*.safetensors`)하여 Git에서 관리 권장.
