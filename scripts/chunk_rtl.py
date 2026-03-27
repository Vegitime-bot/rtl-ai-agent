#!/usr/bin/env python3
"""
chunk_rtl.py
─────────────
Verilog RTL 파일을 논리적 청크(블록) 단위로 분할한다.

청크 종류:
  header     — module 선언 + 파라미터 + 포트 선언
  localparam — localparam 선언 묶음
  decl       — reg / wire / integer 선언 묶음
  assign     — continuous assign 문
  always     — always 블록 (sensitivity 포함)
  footer     — endmodule

출력 JSON 형식:
[
  {
    "kind":    "header" | "localparam" | "decl" | "assign" | "always" | "footer",
    "signals": ["sig_a", "sig_b", ...],   // 이 청크에 등장하는 신호 이름
    "lhs":     ["sig_a"],                 // 이 청크가 값을 쓰는 신호 (always/assign)
    "text":    "...원문...",
    "line_start": 10,
    "line_end":   25,
  },
  ...
]

사용:
  python3 scripts/chunk_rtl.py inputs/origin.v build/rtl_chunks.json
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

VL_KEYWORDS = {
    'begin', 'end', 'if', 'else', 'case', 'casex', 'casez', 'endcase',
    'default', 'assign', 'always', 'posedge', 'negedge', 'or', 'and',
    'not', 'wire', 'reg', 'integer', 'parameter', 'localparam', 'module',
    'endmodule', 'input', 'output', 'inout', 'initial', 'for', 'while',
    'repeat', 'forever', 'task', 'endtask', 'function', 'endfunction',
}

IDENT_RE = re.compile(r'\b([A-Za-z_]\w*)\b')


def strip_comments(text: str) -> str:
    text = re.sub(r'/\*.*?\*/', lambda m: ' ' * len(m.group()), text, flags=re.DOTALL)
    text = re.sub(r'//[^\n]*', '', text)
    return text


def extract_identifiers(text: str) -> list[str]:
    return [t for t in IDENT_RE.findall(text) if t not in VL_KEYWORDS]


def extract_lhs(text: str) -> list[str]:
    """블록에서 LHS에 등장하는 신호 이름 추출 (<=, = 왼쪽)."""
    lhs: list[str] = []
    for m in re.finditer(r'(\w+)\s*(?:\[[^\]]*\])?\s*(?:<=|(?<!=)=(?!=))', text):
        lhs.append(m.group(1))
    return lhs


def find_block_end(text: str, start: int) -> int:
    """'begin' 이후 매칭 'end' 위치 반환. begin이 없으면 세미콜론까지."""
    begin_m = re.search(r'\bbegin\b', text[start:])
    if not begin_m:
        semi = text.find(';', start)
        return semi + 1 if semi != -1 else len(text)

    i = start + begin_m.end()
    depth = 1
    while i < len(text) and depth > 0:
        m = re.search(r'\b(begin|end)\b', text[i:])
        if not m:
            break
        i += m.end()
        depth += 1 if m.group(1) == 'begin' else -1
    return i


def line_of(text: str, pos: int) -> int:
    return text[:pos].count('\n') + 1


def chunk_verilog(source: str) -> list[dict]:
    clean = strip_comments(source)
    chunks: list[dict] = []
    pos = 0

    # ── 1. header: module...); ──
    mod_m = re.search(r'\bmodule\b', clean)
    if mod_m:
        # 파라미터 + 포트 선언 끝까지 (첫 ';' 뒤, 이후 첫 'reg/wire/localparam/always/assign')
        paren_depth = 0
        i = mod_m.start()
        found_open = False
        while i < len(clean):
            if clean[i] == '(':
                paren_depth += 1
                found_open = True
            elif clean[i] == ')':
                paren_depth -= 1
                if found_open and paren_depth == 0:
                    # ');' 까지
                    semi = clean.find(';', i)
                    header_end = semi + 1 if semi != -1 else i + 1
                    header_text = source[mod_m.start():header_end]
                    chunks.append({
                        'kind': 'header',
                        'signals': extract_identifiers(header_text),
                        'lhs': [],
                        'text': header_text.strip(),
                        'line_start': line_of(source, mod_m.start()),
                        'line_end': line_of(source, header_end),
                    })
                    pos = header_end
                    break
            i += 1

    # ── 2. 나머지 블록 파싱 ──
    while pos < len(clean):
        # 다음 키워드 탐색
        m = re.search(
            r'\b(localparam|reg|wire|integer|assign|always|function)\b',
            clean[pos:]
        )
        if not m:
            break
        abs_start = pos + m.start()
        keyword = m.group(1)

        if keyword == 'localparam':
            # ';' 까지
            semi = clean.find(';', abs_start)
            end = semi + 1 if semi != -1 else abs_start + 1
            text = source[abs_start:end]
            chunks.append({
                'kind': 'localparam',
                'signals': extract_identifiers(text),
                'lhs': extract_lhs(text),
                'text': text.strip(),
                'line_start': line_of(source, abs_start),
                'line_end': line_of(source, end),
            })
            pos = end

        elif keyword in ('reg', 'wire', 'integer'):
            # 선언문: ';' 까지 (단, always/assign 키워드 나오기 전)
            semi = clean.find(';', abs_start)
            end = semi + 1 if semi != -1 else abs_start + 1
            text = source[abs_start:end]
            chunks.append({
                'kind': 'decl',
                'signals': extract_identifiers(text),
                'lhs': [],
                'text': text.strip(),
                'line_start': line_of(source, abs_start),
                'line_end': line_of(source, end),
            })
            pos = end

        elif keyword == 'assign':
            semi = clean.find(';', abs_start)
            end = semi + 1 if semi != -1 else abs_start + 1
            text = source[abs_start:end]
            chunks.append({
                'kind': 'assign',
                'signals': extract_identifiers(text),
                'lhs': extract_lhs(text),
                'text': text.strip(),
                'line_start': line_of(source, abs_start),
                'line_end': line_of(source, end),
            })
            pos = end

        elif keyword == 'always':
            end = find_block_end(clean, abs_start)
            text = source[abs_start:end]
            chunks.append({
                'kind': 'always',
                'signals': extract_identifiers(text),
                'lhs': extract_lhs(text),
                'text': text.strip(),
                'line_start': line_of(source, abs_start),
                'line_end': line_of(source, end),
            })
            pos = end

        elif keyword == 'function':
            # function ... endfunction 전체를 하나의 청크로
            end_m2 = re.search(r'\bendfunction\b', clean[abs_start:])
            if end_m2:
                end = abs_start + end_m2.end()
            else:
                end = abs_start + 1
            text = source[abs_start:end]
            # function name 추출
            fn_m = re.search(r'\bfunction\b\s+(?:automatic\s+)?(?:(?:logic|reg|wire|integer|signed|unsigned)\s*)?(?:\[[^\]]*\]\s*)?(\w+)', text)
            fn_name = fn_m.group(1) if fn_m else ""
            chunks.append({
                'kind': 'function',
                'name': fn_name,
                'signals': extract_identifiers(text),
                'lhs': extract_lhs(text),
                'text': text.strip(),
                'line_start': line_of(source, abs_start),
                'line_end': line_of(source, end),
            })
            pos = end

        else:
            pos = abs_start + 1

    # ── 3. footer: endmodule ──
    end_m = re.search(r'\bendmodule\b', clean[pos:])
    if end_m:
        abs_start = pos + end_m.start()
        chunks.append({
            'kind': 'footer',
            'signals': [],
            'lhs': [],
            'text': 'endmodule',
            'line_start': line_of(source, abs_start),
            'line_end': line_of(source, abs_start) + 1,
        })

    return chunks


def main() -> None:
    parser = argparse.ArgumentParser(description='Split Verilog RTL into logical chunks')
    parser.add_argument('rtl', type=Path,
                        help='입력 .v/.sv 파일 또는 디렉토리 (디렉토리면 *.v/*.sv 전체 처리)')
    parser.add_argument('output', type=Path, help='Output JSON')
    args = parser.parse_args()

    # 디렉토리면 하위 *.v / *.sv 전체 수집
    if args.rtl.is_dir():
        files = sorted(args.rtl.glob('*.v')) + sorted(args.rtl.glob('*.sv'))
        if not files:
            raise SystemExit(f'[chunk_rtl] ERROR: {args.rtl} 에 .v/.sv 파일이 없습니다.')
    else:
        files = [args.rtl]

    all_chunks: list[dict] = []
    for f in files:
        source = f.read_text()
        file_chunks = chunk_verilog(source)
        # 파일 출처 기록
        for c in file_chunks:
            c['file'] = str(f)
        all_chunks.extend(file_chunks)
        print(f'[chunk_rtl] {f.name}: {len(file_chunks)} chunks')

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(all_chunks, indent=2))
    print(f'[chunk_rtl] total {len(all_chunks)} chunks → {args.output}')
    for c in all_chunks:
        print(f'  {c["kind"]:12s} L{c["line_start"]:3d}-{c["line_end"]:3d}  lhs={c["lhs"][:3]}')


if __name__ == '__main__':
    main()
