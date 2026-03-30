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
GENVAR_RE = re.compile(r"\bgenvar\s+([\w\s,]+);")          # genvar i, j;
GENERATE_BLOCK_RE = re.compile(
    r"\bgenerate\b(.*?)\bendgenerate\b", re.DOTALL
)
RESERVED  = {
    "if", "else", "begin", "end", "posedge", "negedge",
    "module", "assign", "always", "input", "output", "inout",
    "wire", "reg", "logic", "genvar", "generate", "endgenerate",
    "for", "case", "endcase", "default",
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


def _parse_generate_blocks(body: str) -> list[dict]:
    """
    body 텍스트에서 generate ... endgenerate 블록을 추출.
    각 블록 안의 genvar, 내부 신호 선언, 어사인먼트를 파싱.
    반환: [{"genvar": [...], "signals": [...], "assignments": [...], "raw": str}]
    """
    blocks = []
    for m in GENERATE_BLOCK_RE.finditer(body):
        gen_body = m.group(1)

        # genvar 이름 수집
        genvars: list[str] = []
        for gm in GENVAR_RE.finditer(gen_body):
            names = [n.strip() for n in gm.group(1).split(",") if n.strip()]
            genvars.extend(names)

        # generate 블록 내부 wire/reg/logic 선언
        sigs = [
            {"name": sname, "type": dtype}
            for dtype, sname in DECL_RE.findall(gen_body)
        ]

        # generate 블록 내부 어사인먼트
        assigns = []
        for pfx, lhs, op, rhs in ASSIGN_RE.findall(gen_body):
            assigns.append({
                "lhs": lhs,
                "rhs": extract_tokens(rhs),
                "kind": "assign" if pfx.strip() == "assign" else "always",
            })

        blocks.append({
            "genvar": genvars,
            "signals": sigs,
            "assignments": assigns,
            "raw": gen_body.strip(),
        })
    return blocks


def _parse_genvars_toplevel(body: str) -> list[str]:
    """generate 블록 밖에서 선언된 genvar 도 수집 (genvar i; 형태)."""
    # generate 블록을 공백으로 치환하여 중복 방지
    cleaned = GENERATE_BLOCK_RE.sub(" ", body)
    genvars: list[str] = []
    for gm in GENVAR_RE.finditer(cleaned):
        names = [n.strip() for n in gm.group(1).split(",") if n.strip()]
        genvars.extend(names)
    return genvars


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
        generate_blocks = _parse_generate_blocks(body)
        genvars = _parse_genvars_toplevel(body)

        modules.append({
            "module": mod_name,
            "file": str(path),
            "ports": ports,
            "signals": signals,
            "assignments": assignments,
            "functions": functions,
            "genvars": genvars,
            "generate_blocks": generate_blocks,
        })

    return modules


def diff_signals(origin_modules: list[dict], new_modules: list[dict]) -> dict:
    """
    두 파싱 결과(origin / new)를 비교하여 새로 추가된 신호를 반환.

    반환 예시:
    {
      "MyModule": {
        "added_ports":   [{"direction":"output","name":"out_new","width":"[7:0]"}],
        "added_signals": [{"name":"tmp_wire","type":"wire"}],
      }
    }
    """

    def _index(modules: list[dict]) -> dict[str, dict]:
        return {m["module"]: m for m in modules}

    origin_idx = _index(origin_modules)
    new_idx = _index(new_modules)

    result: dict[str, dict] = {}

    for mod_name, new_mod in new_idx.items():
        origin_mod = origin_idx.get(mod_name, {})

        # ── 포트 비교 (input / output / inout) ─────────────────────────────
        origin_port_names: set[str] = {p["name"] for p in origin_mod.get("ports", [])}
        added_ports = [
            p for p in new_mod.get("ports", [])
            if p["name"] not in origin_port_names
        ]

        # ── 내부 신호 비교 (wire / reg / logic) ────────────────────────────
        origin_sig_names: set[str] = {s["name"] for s in origin_mod.get("signals", [])}
        # generate 블록 내부 신호도 포함
        for gb in origin_mod.get("generate_blocks", []):
            origin_sig_names.update(s["name"] for s in gb.get("signals", []))

        new_sigs = list(new_mod.get("signals", []))
        for gb in new_mod.get("generate_blocks", []):
            new_sigs.extend(gb.get("signals", []))

        added_signals = [s for s in new_sigs if s["name"] not in origin_sig_names]

        # ── genvar 비교 ────────────────────────────────────────────────────
        origin_genvars: set[str] = set(origin_mod.get("genvars", []))
        for gb in origin_mod.get("generate_blocks", []):
            origin_genvars.update(gb.get("genvar", []))

        new_genvars: list[str] = list(new_mod.get("genvars", []))
        for gb in new_mod.get("generate_blocks", []):
            new_genvars.extend(gb.get("genvar", []))

        added_genvars = [g for g in new_genvars if g not in origin_genvars]

        if added_ports or added_signals or added_genvars:
            result[mod_name] = {
                "added_ports": added_ports,
                "added_signals": added_signals,
                "added_genvars": added_genvars,
            }

    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("rtl_dir", type=Path,
                        help="RTL 파일 또는 디렉토리 (origin 또는 단일 모드)")
    parser.add_argument("output", type=Path,
                        help="출력 JSON 경로")
    parser.add_argument("--diff", type=Path, default=None,
                        help="비교할 new RTL 파일/디렉토리. 지정 시 rtl_dir=origin으로 diff 수행")
    args = parser.parse_args()

    def _collect(rtl_path: Path) -> list[dict]:
        data: list[dict] = []
        if rtl_path.is_file():
            files = [rtl_path]
        else:
            files = sorted(list(rtl_path.glob("*.sv")) + list(rtl_path.glob("*.v")))
        for path in files:
            data.extend(parse_file(path))
        return data

    if args.diff:
        # diff 모드: origin vs new → added_signals / added_ports 리포트
        origin_data = _collect(args.rtl_dir)
        new_data = _collect(args.diff)
        diff_result = diff_signals(origin_data, new_data)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(diff_result, indent=2, ensure_ascii=False))
        print(f"[parse_rtl] diff → {args.output}")
    else:
        data = _collect(args.rtl_dir)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"modules": data}, indent=2))
        print(f"[parse_rtl] Wrote {len(data)} modules -> {args.output}")


if __name__ == "__main__":
    main()
