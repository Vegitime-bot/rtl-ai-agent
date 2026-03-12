# Closed-Network Runbook

폐쇄망 Claude Code 환경에서 그대로 수행할 수 있도록 단계별 절차를 정리했습니다.

## 1. 환경 준비
1. **필수 패키지**
   ```bash
   sudo apt update && sudo apt install -y python3.11 python3.11-venv git build-essential
   ```
2. **저장소 클론**
   ```bash
   git clone https://github.com/Vegitime-bot/rtl-ai-agent.git
   cd rtl-ai-agent
   ```
3. **가상환경 및 의존성**
   ```bash
   python3.11 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

## 2. 데이터 인제스트 파이프라인
모든 산출물은 `build/`에 저장됩니다.

```bash
python scripts/parse_rtl.py data/rtl build/rtl_ast.json
python scripts/diff_pseudo.py data/pseudo_old.py data/pseudo_new.py build/pseudo_diff.json
python scripts/chunk_ma.py data/ma_doc.md build/ma_chunks.json
python scripts/build_graph.py build/rtl_ast.json build/causal_graph.json
python rag/ingest.py --db build/rag.db \
  build/rtl_ast.json build/pseudo_diff.json build/ma_chunks.json build/causal_graph.json
```

## 3. 오케스트레이터 실행
- **LLM 없이**
  ```bash
  python orchestrator/flow.py --ip AES --db build/rag.db
  ```
- **OpenAI-Compatible 엔드포인트 사용 시**
  1. `models/config.yaml` 편집 또는 `MODEL_API_KEY` 환경변수 지정
  2. 실행
     ```bash
     python orchestrator/flow.py --ip AES --db build/rag.db --model-config models/config.yaml
     ```

결과물: `outputs/analysis.md`, `outputs/bundle.json`

## 4. 입력 데이터 교체
| 유형 | 위치 | 교체 후 실행해야 할 스크립트 |
| --- | --- | --- |
| RTL | `data/rtl/*.sv` | `parse_rtl.py`, `build_graph.py`, `rag/ingest.py` |
| Pseudo | `data/pseudo_old.py`, `data/pseudo_new.py` | `diff_pseudo.py`, `rag/ingest.py` |
| MA 문서 | `data/ma_doc.md` (또는 추가 파일) | `chunk_ma.py`, `rag/ingest.py` |

## 5. 로그 & 산출물
- `build/rtl_ast.json` : 모듈/포트/신호/할당 정보
- `build/causal_graph.json` : 신호 간 causal edge 리스트
- `outputs/analysis.md` : Spec findings + Action plan + LLM summary(선택)
- `outputs/bundle.json` : 전체 결과를 JSON으로 묶은 파일

## 6. 문제 해결 체크리스트
1. **의존성 미설치** → `pip install -r requirements.txt`
2. **LLM 호출 실패** → `models/config.yaml` endpoint/키 확인, `MODEL_API_KEY` 설정
3. **새 데이터 반영 안 됨** → 인제스트 파이프라인 전체(2단계) 재실행
4. **경로 문제** → 모든 명령은 레포 루트(`rtl-ai-agent/`)에서 실행

이 Runbook을 Claude Code 내부에 그대로 복사해 두면, 추가 지시 없이 재현할 수 있습니다.
