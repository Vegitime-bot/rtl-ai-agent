# RTL AI Agent MVP

초기 실험용으로 만든 경량 환경입니다. Debian WSL에서 `git clone` 후 바로 실행해 볼 수 있습니다. 폐쇄망 Claude Code용 절차는 [`docs/RUNBOOK.md`](docs/RUNBOOK.md)를 참고하세요.

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
python scripts/parse_rtl.py inputs build/rtl_ast.json
python scripts/diff_pseudo.py inputs/algorithm_origin.py inputs/algorithm_new.py build/pseudo_diff.json
python scripts/chunk_ma.py inputs/uArch_origin.txt build/uarch_origin.json
python scripts/chunk_ma.py inputs/uArch_new.txt build/uarch_new.json
python scripts/build_graph.py build/rtl_ast.json build/causal_graph.json
python rag/ingest.py --db build/rag.db \
  build/rtl_ast.json build/pseudo_diff.json build/uarch_origin.json build/uarch_new.json build/causal_graph.json
```

## 4. 번들 생성 & 오케스트레이션 실행

```bash
python orchestrator/flow.py --ip demo --db build/rag.db
```

실행하면 `outputs/` 폴더에 요구사항 분석, 설계 계획, 리포트가 생성됩니다.

### 4-1. 원클릭 데모 실행
사내 Claude Code 등에서 **셋업(1회)**과 **실행(반복)**을 명확히 나눠 사용할 수 있습니다.

**Setup – 최초 1회만**
```bash
git clone https://github.com/Vegitime-bot/rtl-ai-agent.git
cd rtl-ai-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Run – 매번 반복할 때**
```bash
source .venv/bin/activate          # 새 셸이면 다시 활성화
./scripts/run_demo_pipeline.sh      # 기본 DB 경로 build/rag.db 사용
# 또는
./scripts/run_demo_pipeline.sh build/demo.db --model-config models/config.yaml --generate-rtl --output-rtl outputs/new.v
```

- 첫 번째 인자는 RAG DB 경로(선택), 이후 인자는 그대로 `orchestrator/flow.py`에 전달됩니다.
- 종료 후 `outputs/analysis.md`와 bundle 파일을 바로 확인할 수 있습니다.

## 5. LLM 연동 (선택)

1. `pip install -r requirements.txt` (requests + PyYAML 포함)  
2. `models/config.yaml` 수정:
   ```yaml
   endpoint: https://your-endpoint/v1
   model: llama-3
   api_key: sk-...
   ```
   - API 키를 파일에 적기 싫으면 `MODEL_API_KEY` 환경변수로 전달 가능.
3. 실행 시 `--model-config models/config.yaml` 옵션 추가:
   ```bash
   python orchestrator/flow.py --ip demo --db build/rag.db --model-config models/config.yaml
   ```
   → 보고서 마지막에 LLM 요약 섹션이 추가됨.
4. **RTL 생성 및 검증까지 수행하려면**
   ```bash
   python orchestrator/flow.py --ip demo --db build/rag.db \
     --model-config models/config.yaml --generate-rtl --output-rtl outputs/new.v
   ```
   - `outputs/new.v`가 생성되며, 기본 검증 결과가 콘솔/`bundle.json`에 기록됨.

## 6. 입력 파일 커스터마이즈

| 유형 | 위치 | 교체 후 실행해야 할 스크립트 |
| --- | --- | --- |
| RTL | `inputs/origin.v` | `parse_rtl.py`, `build_graph.py`, `rag/ingest.py` |
| Pseudo | `inputs/algorithm_origin.py`, `inputs/algorithm_new.py` | `diff_pseudo.py`, `rag/ingest.py` |
| MA 문서 | `inputs/uArch_origin.txt`, `inputs/uArch_new.txt` | 각각 `chunk_ma.py`, `rag/ingest.py` |

## 7. 구조

```
├── inputs/             # origin.v + uArch/algorithm 원본/신규
├── scripts/            # 인제스트 + 그래프 빌더
├── rag/                # 간단한 SQLite 기반 RAG
├── orchestrator/       # 플로우, 코드 생성, 검증
├── models/             # 모델 설정 템플릿
├── docs/               # Runbook 등 문서
├── build/              # 생성되는 산출물 (git ignore)
└── outputs/            # 리포트/신규 RTL (git ignore)
```

## 8. LSP 서버 (실험)

분석/그래프 정보를 IDE에서 바로 조회할 수 있도록 간단한 LSP 서버를 추가했습니다.

```bash
python -m lsp.rtl_ai_server  # stdio 모드로 실행
```

- VS Code 등에서 `stdio` 기반 커맨드로 연결하거나, Claude Code MCP와 연동해 메타데이터를 조회할 수 있습니다.
- `hover`에서는 신호 타입/폭을, `rtl-ai/getContext` 명령에서는 연결된 causal edge 목록을 받을 수 있습니다.

## 9. 다음 단계 아이디어
- 실제 RTL 파서(Surelog) 연동
- 오픈소스 LLM(vLLM + Llama 3 등) 엔드포인트 연결
- 시뮬레이터/ formal 도구 CLI 래퍼 추가
- GitOps/CI 파이프라인 연동

이 초기 버전을 바탕으로 사내 인프라에 맞게 확장하면 됩니다.
