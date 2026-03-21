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
python scripts/parse_rtl.py inputs build/rtl_ast.json
python scripts/diff_pseudo.py inputs/algorithm_origin.py inputs/algorithm_new.py build/pseudo_diff.json
python scripts/chunk_ma.py inputs/uArch_origin.txt build/uarch_origin.json
python scripts/chunk_ma.py inputs/uArch_new.txt build/uarch_new.json
python scripts/build_graph.py build/rtl_ast.json build/causal_graph.json
python rag/ingest.py --db build/rag.db \
  build/rtl_ast.json build/pseudo_diff.json build/uarch_origin.json build/uarch_new.json build/causal_graph.json
```

## 3. 오케스트레이터 실행
- **LLM 없이 분석만**
  ```bash
  python orchestrator/flow.py --ip AES --db build/rag.db
  ```
- **LLM 연동 (요약만)**
  ```bash
  # models/config.yaml 예시 (OpenAI 호환)
  # provider: openai / endpoint: https://api.anthropic.com/v1 / model: claude-sonnet-4-6
  python orchestrator/flow.py --ip AES --db build/rag.db --model-config models/config.yaml
  ```
- **RTL 생성 + 검증까지**
  ```bash
  python orchestrator/flow.py --ip AES --db build/rag.db \
    --model-config models/config.yaml --generate-rtl --output-rtl outputs/new.v
  ```
- **멀티 .v 파일 입력 (디렉토리 지정)**
  ```bash
  # inputs/ 디렉토리에 있는 모든 *.v / *.sv 파일이 자동으로 포함됩니다.
  python orchestrator/flow.py --ip AES --origin-rtl-dir inputs/ \
    --model-config models/config.yaml --generate-rtl
  ```
  `inputs/` 디렉토리에 `.v` 또는 `.sv` 파일을 추가하기만 하면 파일명 알파벳 순서로 자동 포함됩니다.
  각 파일은 프롬프트 내에서 `=== RTL: <filename> ===` 헤더로 구분됩니다.

결과물: `outputs/analysis.md`, `outputs/bundle.json`, `outputs/new.v`(선택)

> 참고: `models/config.yaml`의 `provider` 값을 `claude`(Anthropic native) 또는 `openai`(OpenAI 호환) 중에서 택할 수 있습니다. 엔드포인트와 모델명을 환경에 맞게 조정하세요.

## 4. 입력 파일 교체
| 유형 | 위치 | 교체 후 실행해야 할 스크립트 |
| --- | --- | --- |
| RTL | `inputs/` 디렉토리의 `*.v` / `*.sv` 파일 | `parse_rtl.py`, `build_graph.py`, `rag/ingest.py` |
| Pseudo | `inputs/algorithm_origin.py`, `inputs/algorithm_new.py` | `diff_pseudo.py`, `rag/ingest.py` |
| Micro-Architecture 문서 | `inputs/uArch_origin.txt`, `inputs/uArch_new.txt` | 각각 `chunk_ma.py`, `rag/ingest.py` |

## 5. 로그 & 산출물
- `build/rtl_ast.json` : 모듈/포트/신호/할당 정보
- `build/causal_graph.json` : 신호 간 causal edge 리스트
- `outputs/analysis.md` : Spec findings + Action plan + LLM summary
- `outputs/new.v` : LLM이 생성한 RTL(선택)
- `outputs/bundle.json` : 전체 결과를 JSON으로 묶은 파일

## 6. 문제 해결 체크리스트
1. **의존성 미설치** → `pip install -r requirements.txt`
2. **LLM 호출 실패** → `models/config.yaml` endpoint/키 확인, `MODEL_API_KEY` 설정
3. **새 데이터 반영 안 됨** → 인제스트 파이프라인 전체(2단계) 재실행
4. **경로 문제** → 모든 명령은 레포 루트(`rtl-ai-agent/`)에서 실행

## 7. Graph Hops 설정

`--graph-hops` 옵션으로 Neo4j 인과 그래프 탐색 깊이를 제어합니다.

| 값 | 동작 | 적합한 상황 |
|---|---|---|
| `--graph-hops 1` (기본값) | 직접 연결된 1-hop driver/dependent만 조회 | 빠른 분석, 대부분의 케이스 |
| `--graph-hops 2` | 1-hop 이웃의 이웃까지 포함한 2-hop 조회 | 복잡한 버그 추적, 광범위 인과관계 파악 |

**Output port 자동 2-hop 처리**: RTL 모듈의 output port로 지정된 신호는 `--graph-hops` 설정값에 +1을 자동 적용합니다. 예를 들어 `--graph-hops 1`이면 일반 신호는 1-hop, output port는 2-hop으로 조회합니다. 이는 출력 신호의 상위 드라이버 체인까지 파악하기 위한 설계입니다.

```bash
# 기본 실행 (1-hop, output port는 2-hop 자동 적용)
python orchestrator/flow.py --ip AES --graph-hops 1

# 2-hop 명시 (output port는 3-hop)
python orchestrator/flow.py --ip AES --graph-hops 2
```

실행 시 적용된 hop 설정이 로그로 출력됩니다:
```
[flow] graph hops: 1 (output ports: 2)
```

## 8. LSP 서버 (옵션)
```bash
python -m lsp.rtl_ai_server
```
- stdio 모드로 실행되며, IDE에서 hover/context 정보를 요청할 수 있다.

이 Runbook을 Claude Code 내부에 그대로 복사해 두면, 추가 지시 없이 재현할 수 있습니다.
