# RTL AI Agent MVP

초기 실험용으로 만든 경량 환경입니다. Debian WSL에서 `git clone` 후 바로 실행해 볼 수 있습니다.

## 1. 준비 사항

```bash
sudo apt update && sudo apt install -y python3.11 python3.11-venv git build-essential
```

## 2. 레포 클론 & 가상환경

```bash
git clone https://github.com/Vegitime-bot/rtl-ai-agent.git
cd rtl-ai-agent
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 3. 샘플 데이터 인제스트

```bash
python scripts/parse_rtl.py data/rtl build/rtl_ast.json
python scripts/diff_pseudo.py data/pseudo_old.py data/pseudo_new.py build/pseudo_diff.json
python scripts/chunk_ma.py data/ma_doc.md build/ma_chunks.json
python rag/ingest.py --db build/rag.db build/rtl_ast.json build/pseudo_diff.json build/ma_chunks.json
```

## 4. 번들 생성 & 오케스트레이션 실행

```bash
python orchestrator/flow.py --ip demo --db build/rag.db
```

실행하면 `outputs/` 폴더에 요구사항 분석, 설계 계획, 리포트가 생성됩니다.

## 5. LLM 연동 (선택)

`models/config.yaml`에 OpenAI-Compatible 엔드포인트를 적으면, `flow.py`가 해당 API를 호출하도록 확장할 수 있습니다. 기본값은 오프라인 모드입니다.

## 6. 구조

```
├── data/                # 샘플 RTL/pseudo/문서
├── scripts/             # 인제스트 스크립트
├── rag/                 # 간단한 벡터스토어 대체(SQLite)
├── orchestrator/        # 파이프라인 + 에이전트 스텁
├── models/              # 모델 설정 템플릿
├── build/               # 생성되는 산출물 (git ignore)
└── outputs/             # 리포트 출력 (git ignore)
```

## 7. 다음 단계 아이디어
- 실제 RTL 파서(Surelog) 연동
- 오픈소스 LLM(vLLM + Llama 3 등) 엔드포인트 연결
- 시뮬레이터/ formal 도구 CLI 래퍼 추가
- GitOps/CI 파이프라인 연동

이 초기 버전을 바탕으로 사내 인프라에 맞게 확장하면 됩니다.
