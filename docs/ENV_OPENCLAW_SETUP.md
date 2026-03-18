# RTL AI Agent – OpenClaw 개발 환경 세팅

## 1. 공통 전제
- Python 3.11 이상
- Surelog + `UHDM.capnp` (Homebrew 예: `brew install surelog capnp`)
- `MODEL_API_KEY` 환경변수에 LLM 키 저장 (예: `export MODEL_API_KEY='sk-...'`)

## 2. 의존성 설치
```bash
cd projects/rtl-ai-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # requests, PyYAML, pygls>=2.0.1, neo4j 등
```

## 3. RTL 파이프라인
```bash
python scripts/run_surelog.py inputs/origin.v
python scripts/uhdm_extract.py build/origin.uhdm.json --output build/rtl_ast.json
python scripts/build_graph.py build/rtl_ast.json build/causal_graph.json
python rag/ingest.py --db build/rag.db \
  build/rtl_ast.json build/pseudo_diff.json \
  build/uarch_origin.json build/uarch_new.json build/causal_graph.json
python orchestrator/flow.py --ip demo --db build/rag.db \
  --model-config models/config.yaml --generate-rtl --output-rtl outputs/new.v
```

## 4. LSP / IDE 통합
```bash
python -m lsp.rtl_ai_server  # stdio 기반
```
- pygls 2.x + lsprotocol 기반, IDE나 Claude MCP에서 stdio로 연결.

## 5. Neo4j 적재 (외부 Bolt URI 확보 시)
```bash
python scripts/neo4j_ingest.py \
  --uri bolt://<host>:7687 \
  --user neo4j --password '<pwd>' \
  --module tcon_basic --clear
```
> 현재 OpenClaw 호스트에는 Neo4j 서버가 없으므로, 원격 Bolt URI/계정을 받아 접속해야 합니다.
