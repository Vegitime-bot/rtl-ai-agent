# Progress Log

## 2026-03-12
- 확정된 입출력(`origin.v` 등) 기반으로 코드 생성/검증 파이프라인 설계 시작.

## 2026-03-13
- 코드 생성(`orchestrator/codegen.py`) + 검증(`verify.py`) 추가, README/Runbook 갱신.
- pygls 기반 LSP 서버 도입, 문서화.

## 2026-03-14
- Surelog 빌드 완료, `origin.v → UHDM JSON` 추출 테스트.
- UHDM JSON을 내부 모듈/신호/assign 포맷으로 변환하는 스크립트 작성 및 디버깅 중.
