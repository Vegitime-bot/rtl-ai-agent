# inputs/algorithm/

알고리즘 스펙 파일 디렉토리.

```
inputs/algorithm/
  origin/   ← 변경 전 알고리즘 파일들 (*.py, *.txt)
  new/      ← 변경 후 알고리즘 파일들 (*.py, *.txt)
```

## 파일 추가 방법

여러 파일을 자유롭게 추가하면 됩니다. 파이프라인이 모든 파일을 자동으로 수집합니다.

```bash
# 예시
inputs/algorithm/origin/
  pixel_pipeline.py
  gain_control.py
  noise_reduction.py

inputs/algorithm/new/
  pixel_pipeline.py    ← 변경된 파일
  gain_control.py      ← 변경된 파일
  noise_reduction.py   ← 동일하면 diff 없음
  hdr_merge.py         ← 신규 추가
```

## 매칭 규칙

- origin/ 과 new/ 의 **파일명이 같은 것끼리** 매칭하여 diff 생성
- origin에만 있으면 → 삭제된 파일로 처리
- new에만 있으면   → 신규 파일로 처리
- 양쪽 모두 있으면 → unified diff

## 환경변수로 경로 변경 가능

```bash
ALGO_ORIGIN_DIR=/other/path/origin bash scripts/run_full_pipeline.sh
```
