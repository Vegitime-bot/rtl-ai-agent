# RTL AI Agent – Progress Tracker

| Timestamp (KST) | Stage | Details | Owner |
|-----------------|-------|---------|-------|
| 2026-03-15 16:45 | INIT | Surelog 래퍼(`scripts/run_surelog.py`) 추가, UHDM → JSON 변환 자동화 | agent |
| 2026-03-15 17:35 | WIP  | `uhdm_extract.py` 구현 중 – UHDM JSON → 모듈/신호 그래프 정제 | agent |
| 2026-03-16 04:45 | BUILD | `run_surelog.py` 최신화, UHDM capnp 변환 및 `logs/commands.log` 자동 기록 | agent |
| 2026-03-16 05:25 | WIP  | `uhdm_extract.py` + `build_graph.py` 연동, 모듈/edge 구조 검증 진행 중 | agent |
| 2026-03-16 21:05 | WIP  | UHDM extractor 프로파일링, parent chain 캐시/타입 매핑 정리 | agent |
| 2026-03-17 01:10 | BUILD | `uhdm_extract.py` 정식 정리(캐시 + 로그 제거) 및 `build_graph.py` 재검증 | agent |
