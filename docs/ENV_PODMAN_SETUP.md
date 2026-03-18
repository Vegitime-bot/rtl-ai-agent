# RTL AI Agent – 사내 Podman 환경 세팅

## 1. 사전 준비
- Git 접근 권한 + Python 3.11 이상
- Surelog & capnp 설치 (예: `sudo yum install surelog capnproto`)
- LLM 키: `export MODEL_API_KEY='sk-...'`

## 2. 레포/가상환경
```bash
git clone https://github.com/Vegitime-bot/rtl-ai-agent.git
cd rtl-ai-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## 3. RTL 파이프라인
OpenClaw와 동일한 순서로 실행:
```bash
python scripts/run_surelog.py inputs/origin.v
python scripts/uhdm_extract.py build/origin.uhdm.json --output build/rtl_ast.json
python scripts/build_graph.py build/rtl_ast.json build/causal_graph.json
python rag/ingest.py --db build/rag.db [...]  # 동일한 인자 사용
python orchestrator/flow.py --ip demo --db build/rag.db \
  --model-config models/config.yaml --generate-rtl --output-rtl outputs/new.v
```

### 원클릭 스크립트 (Podman 환경)
```bash
export MODEL_API_KEY='sk-...'
export NEO4J_PASSWORD='...'
./scripts/run_full_pipeline.sh
```
- `config/neo4j.yaml` 값을 필요에 맞게 수정하거나, `NEO4J_CONFIG` 환경변수로 다른 파일을 지정할 수 있습니다.

## 4. Neo4j (Podman 기반)
```bash
podman run -d --name neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/superSecret! \
  -v /srv/neo4j-data:/data \
  -v /srv/neo4j-logs:/logs \
  neo4j:5.18
```
- Bolt URI: `neo4j://<사내호스트>:7687` 또는 `bolt://...`
- 외부 접속이 필요하면 `conf/neo4j.conf`에서 `dbms.default_listen_address=0.0.0.0` 설정.

## 5. Neo4j 적재
```bash
python scripts/neo4j_ingest.py --config config/neo4j.yaml
```
- `password_env`를 쓰면 `export NEO4J_PASSWORD=...` 만으로 인증.
- 모듈별 적재를 원하면 `--module <module_name>` 추가.

## 6. 검증
```bash
cypher-shell -a neo4j://<사내호스트>:7687 -u neo4j -p superSecret! "MATCH (s:Signal) RETURN count(s);"
```
결과 파일은 `outputs/`에 생성되며, 필요 시 사내 파이프라인으로 전달합니다.
