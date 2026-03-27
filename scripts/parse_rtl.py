#!/usr/bin/env python3
"""RTL parser — module/port/signal/assignment 추출.

지원:
  - module foo #(parameter ...) (port ...); ... endmodule
  - 하나의 파일에 module 여러 개
  - parameter 블록 내 중첩 괄호
  - port 선언: ANSI style (input/output/inout을 port 목록 안에 직접)
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

IDENT_RE  = re.compile(r"[A-Za-z_][\w$]*")
FUNC_RE   = re.compile(
    r'\bfunction\b\s+'                           # function keyword
    r'(?:automatic\s+)?'                         # optional automatic
    r'(?:(?:logic|reg|wire|integer|signed|unsigned)\s*)?'  # optional return type
    r'(?:\[[^\]]*\]\s*)?'                        # optional width
    r'(\w+)'                                     # function name
)
PORT_RE   = re.compile(
    r"(input|output|inout)\s+"                          # direction
    r"(?:wire|reg|logic|signed|unsigned)?\s*"           # optional type (non-capturing)
    r"(?:\[[^\]]*\]\s*)?"                               # optional width [N:0]
    r"([A-Za-z_]\w*)"                                   # port name (must start with letter/_)
)
DECL_RE   = re.compile(r"\b(logic|wire|reg)\s*(?:\[[^\]]*\])?\s*(\w+)")
ASSIGN_RE = re.compile(r"(assign\s+)?(\w+)\s*(?:\[[^\]]*\])?\s*(<=|=)\s*([^;]+);")
RESERVED  = {
    "if", "else", "begin", "end", "posedge", "negedge",
    "module", "assign", "always", "input", "output", "inout",
    "wire", "reg", "logic",
}


def _skip_balanced(text: str, pos: int, open_ch: str = "(", close_ch: str = ")") -> int:
    """pos는 open_ch 위치. 짝이 맞는 close_ch 다음 위치를 반환."""
    depth = 0
    for i in range(pos, len(text)):
        if text[i] == open_ch:
            depth += 1
        elif text[i] == close_ch:
            depth -= 1
            if depth == 0:
                return i + 1
    return len(text)


def _find_modules(text: str):
    """
    text에서 module ... endmodule 블록을 순서대로 추출.
    yields (name, param_text, port_text, body_text)
    """
    i = 0
    while True:
        m = re.search(r'\bmodule\s+(\w+)\s*', text[i:])
        if not m:
            break
        name = m.group(1)
        pos = i + m.end()

        # optional #( parameter block )
        param_text = ""
        if pos < len(text) and text[pos] == "#":
            pos += 1
            if pos < len(text) and text[pos] == "(":
                end = _skip_balanced(text, pos)
                param_text = text[pos+1:end-1]
                pos = end

        # skip whitespace
        while pos < len(text) and text[pos].isspace():
            pos += 1

        # ( port list )
        if pos >= len(text) or text[pos] != "(":
            i = i + m.end()
            continue
        port_end = _skip_balanced(text, pos)
        port_text = text[pos+1:port_end-1]
        pos = port_end

        # find ';' after port list (end of module header)
        semi = text.find(";", pos)
        if semi == -1:
            break
        pos = semi + 1

        # find matching endmodule
        end_m = re.search(r'\bendmodule\b', text[pos:])
        if not end_m:
            break
        body_text = text[pos:pos + end_m.start()]
        i = pos + end_m.end()

        yield name, param_text, port_text, body_text


_VERILOG_LITERAL_RE = re.compile(
    r"\d+'[bBoOdDhH][0-9a-fA-FxXzZ_]+"  # ex: 8'b0, 16'hFF, 1'b1
    r"|\b\d+\b"                           # 순수 정수
)

def extract_tokens(expr: str) -> list[str]:
    """RHS 표현식에서 유효한 신호명만 추출. 숫자 리터럴(1'b0 등)은 제외."""
    # 리터럴 먼저 제거 후 식별자 추출
    cleaned = _VERILOG_LITERAL_RE.sub(' ', expr)
    return [t for t in IDENT_RE.findall(cleaned) if t not in RESERVED]


def _strip_comments(text: str) -> str:
    # block comments
    text = re.sub(r'/\*.*?\*/', ' ', text, flags=re.DOTALL)
    # line comments
    text = re.sub(r'//[^\n]*', ' ', text)
    return text


def _parse_functions(body: str) -> list[dict]:
    """
    body 텍스트에서 function ... endfunction 블록을 추출.
    반환: [{"name", "inputs", "outputs", "signals", "assignments"}]
    """
    funcs = []
    i = 0
    while True:
        fm = re.search(r'\bfunction\b', body[i:])
        if not fm:
            break
        abs_start = i + fm.start()
        # function name
        name_m = FUNC_RE.search(body[abs_start:abs_start + 200])
        fname = name_m.group(1) if name_m else "unknown"

        # find endfunction
        end_m = re.search(r'\bendfunction\b', body[i + fm.end():])
        if not end_m:
            break
        abs_end = i + fm.end() + end_m.end()
        func_body = body[abs_start:abs_end]

        # inputs/outputs inside function
        inputs  = [m.group(1) for m in re.finditer(r'\binput\s+(?:\w+\s+)?(?:\[[^\]]*\]\s*)?(\w+)', func_body)]
        outputs = [m.group(1) for m in re.finditer(r'\boutput\s+(?:\w+\s+)?(?:\[[^\]]*\]\s*)?(\w+)', func_body)]

        # internal reg/wire/logic
        sigs = []
        for dtype, sname in DECL_RE.findall(func_body):
            if sname != fname:  # function 이름 자체는 제외
                sigs.append({"name": sname, "type": dtype})

        # assignments inside function
        assigns = []
        for pfx, lhs, op, rhs in ASSIGN_RE.findall(func_body):
            assigns.append({
                "lhs": lhs,
                "rhs": extract_tokens(rhs),
                "kind": "assign" if pfx.strip() == "assign" else "always",
            })

        funcs.append({
            "name": fname,
            "inputs": inputs,
            "outputs": outputs,
            "signals": sigs,
            "assignments": assigns,
        })
        i = abs_end

    return funcs


def parse_file(path: Path) -> list[dict]:
    raw  = path.read_text(encoding="utf-8", errors="replace")
    text = _strip_comments(raw)

    modules = []
    for mod_name, param_text, port_text, body in _find_modules(text):
        # ports
        ports = []
        seen_ports: set[str] = set()
        for direction, pname in PORT_RE.findall(port_text):
            if pname not in seen_ports:
                seen_ports.add(pname)
                # width 재추출: direction ~ pname 사이의 [N:0] 검색
                w_m = re.search(
                    rf'{direction}\s+(?:wire|reg|logic|signed|unsigned)?\s*(\[[^\]]*\])?\s*{re.escape(pname)}',
                    port_text
                )
                width = w_m.group(1) if (w_m and w_m.group(1)) else "1"
                ports.append({"direction": direction, "name": pname, "width": width})

        # signals (body)
        signals = []
        for dtype, sname in DECL_RE.findall(body):
            signals.append({"name": sname, "type": dtype})

        # assignments
        assignments = []
        for pfx, lhs, op, rhs in ASSIGN_RE.findall(body):
            assignments.append({
                "lhs": lhs,
                "rhs": extract_tokens(rhs),
                "kind": "assign" if pfx.strip() == "assign" else "always",
            })

        functions = _parse_functions(body)

        modules.append({
            "module": mod_name,
            "file": str(path),
            "ports": ports,
            "signals": signals,
            "assignments": assignments,
            "functions": functions,
        })

    return modules


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("rtl_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    data: list[dict] = []
    rtl_dir = args.rtl_dir
    if rtl_dir.is_file():
        files = [rtl_dir]
    else:
        files = sorted(list(rtl_dir.glob("*.sv")) + list(rtl_dir.glob("*.v")))

    for path in files:
        data.extend(parse_file(path))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"modules": data}, indent=2))
    print(f"[parse_rtl] Wrote {len(data)} modules -> {args.output}")


if __name__ == "__main__":
    main()
