# RTL AI Agent — 프로젝트 정의서

_최종 업데이트: 2026-03-20_

---

## 1. 프로젝트 목적

**스펙 변경(uArch, Algorithm)을 입력으로 받아, 기존 RTL에서 올바른 새 RTL을 자동으로 생성하는 AI Agent를 구축한다.**

이 Agent는 반도체 설계 엔지니어의 반복적인 RTL 수정 작업을 자동화하는 것을 목표로 한다.

---

## 2. 입력 / 출력

### 입력 (4종 쌍)

| 파일 | 내용 |
|---|---|
| `inputs/origin.v` | 기존 RTL (Verilog) |
| `inputs/uArch_origin.txt` | 기존 마이크로아키텍처 스펙 |
| `inputs/uArch_new.txt` | 변경된 마이크로아키텍처 스펙 |
| `inputs/algorithm_origin.py` | 기존 동작 모델 (Python golden model) |
| `inputs/algorithm_new.py` | 변경된 동작 모델 (Python golden model) |

### 출력

| 파일 | 내용 |
|---|---|
| `outputs/new.v` | 스펙 변경사항이 반영된 새 RTL (Verilog) |
| `outputs/analysis.md` | 변경 분석 리포트 |
| `outputs/bundle.json` | 전체 파이프라인 산출물 묶음 |

---

## 3. 파이프라인 구조

```
[입력 파일들]
    │
    ▼
┌─────────────────────────────────────────┐
│  BUILD PHASE                            │
│                                         │
│  parse_rtl.py       → rtl_ast.json     │  RTL 구조 파싱 (Surelog/UHDM 기반)
│  build_graph.py     → causal_graph.json│  신호 인과관계 그래프 추출
│  neo4j_ingest.py    → Neo4j DB         │  그래프 DB 저장
│  diff_pseudo.py     → pseudo_diff.json │  알고리즘 변경점 추출
│  chunk_ma.py        → uarch_*.json     │  uArch 스펙 청크화
│  rag/ingest.py      → rag.db           │  RAG 인덱스 구축 (SQLite)
└─────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────┐
│  INFERENCE PHASE (orchestrator/flow.py) │
│                                         │
│  spec_agent    : 스펙 diff 분석         │
│  plan_agent    : 변경 액션 플랜 생성    │
│  neo4j_query   : 신호 인과관계 LLM 주입│  ← 핵심 컨텍스트
│  codegen       : LLM → new.v 생성      │
│  verify        : 생성 결과 검증         │
└─────────────────────────────────────────┘
    │
    ▼
[outputs/new.v]
```

---

## 4. 핵심 기술 요소

| 요소 | 역할 |
|---|---|
| **Surelog / UHDM** | RTL을 정식 AST로 파싱 |
| **Causal Graph (Neo4j)** | 신호 간 인과관계(`DRIVES` 엣지)를 그래프 DB로 관리 |
| **RAG (SQLite)** | 스펙 문서 청크를 검색 가능하게 인덱싱 |
| **LLM (Claude / OpenAI)** | 분석 + RTL 코드 생성 |
| **Neo4j Graph Context** | LLM 프롬프트에 신호 인과관계를 주입해 생성 품질 향상 |

---

## 5. 현재 구현 상태 (2026-03-20 기준)

| 단계 | 상태 | 비고 |
|---|---|---|
| RTL 파싱 (Surelog/UHDM) | ✅ 완료 | `rtl_ast.json` 생성 |
| 신호 인과관계 그래프 | ✅ 완료 | Neo4j + `causal_graph.json` |
| 알고리즘 diff 분석 | ✅ 완료 | `pseudo_diff.json` |
| uArch 스펙 분석 | ✅ 완료 | RAG 청크화 |
| LLM RTL 생성 | ✅ 완료 | `outputs/new.v` |
| Neo4j 컨텍스트 주입 | ✅ 완료 | LLM 프롬프트에 1-hop 그래프 주입 |
| 생성 결과 검증 | ⚠️ 미흡 | `TODO` 유무 + `module` 키워드만 체크 |
| 신호 구조 검증 | 🔧 개선 중 | `verify_causal.py` 작성 완료 (미통합) |

---

## 6. 현재 한계 및 개선 방향

### 6-1. 검증 강화 (최우선)

현재 `orchestrator/verify.py`의 검증은 사실상 형식 체크 수준이다.

**개선 방향:**
- `verify_causal.py` 통합: 생성된 RTL의 신호 의존성이 원본 causal graph + 신규 스펙과 일치하는지 자동 체크
- 검증 실패 시 재생성 루프: Agent가 스스로 수정 후 재시도

### 6-2. 긴 RTL 대응

- 현재 파이프라인은 전체 RTL을 LLM에 통째로 넣는 방식
- RTL이 커질수록 컨텍스트 윈도우 초과 위험 존재
- **개선 방향:** 변경 영향 범위(diff scope) 기반 청크 선택적 주입

### 6-3. 2-hop 그래프 컨텍스트

- 현재 Neo4j에서 1-hop 이웃만 LLM에 주입
- 출력 포트 같은 중요 신호는 2-hop까지 확장 검토

---

## 7. 범위 외 (Out of Scope)

- RTL 시뮬레이션 실행 (waveform, testbench)
- Formal verification
- 합성(synthesis) 결과 검증
- 입/출력 값 레벨의 기능 검증

> 이 프로젝트의 검증은 **구조적 정확성(신호 구조, 스펙 반영 여부)** 에 집중하며,
> 동작 레벨(simulation) 검증은 별도 도구의 역할이다.

---

## 8. 브랜치 구조

| 브랜치 | 내용 |
|---|---|
| `main` | 안정 버전 |
| `apply_neo4j` | Neo4j 인과관계 그래프 통합 작업 |
