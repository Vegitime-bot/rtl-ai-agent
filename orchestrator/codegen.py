from __future__ import annotations

import json
import re
import sys
import warnings
from pathlib import Path

from llm_utils import call_llm


_ALGO_SUFFIXES = {".py", ".txt", ".sv", ".v"}


def _read_rtl_sources(origin_rtl_dir: Path) -> str:
    """Read all *.v / *.sv from a directory, or a single file, for LLM prompting."""
    if origin_rtl_dir.is_file():
        return origin_rtl_dir.read_text()
    files = sorted(
        list(origin_rtl_dir.glob("*.v")) + list(origin_rtl_dir.glob("*.sv")),
        key=lambda p: p.name,
    )
    if not files:
        raise FileNotFoundError(f"No *.v / *.sv files found in {origin_rtl_dir}")
    parts: list[str] = []
    for f in files:
        parts.append(f"=== RTL: {f.name} ===")
        parts.append(f.read_text())
    return "\n".join(parts)


def _read_algo_sources(algo_path: Path, label: str = "Algorithm") -> str:
    """
    알고리즘 파일 또는 디렉토리를 읽어 하나의 문자열로 반환.
    - 단일 파일: 그대로 읽기
    - 디렉토리: 하위 .py / .txt 파일을 정렬 후 연결
    """
    if algo_path.is_file():
        return algo_path.read_text(encoding="utf-8")
    if algo_path.is_dir():
        files = sorted(
            f for f in algo_path.iterdir()
            if f.is_file() and f.suffix in _ALGO_SUFFIXES
        )
        if not files:
            raise FileNotFoundError(f"No algorithm files found in {algo_path}")
        parts: list[str] = []
        for f in files:
            parts.append(f"=== {label}: {f.name} ===")
            parts.append(f.read_text(encoding="utf-8"))
        return "\n".join(parts)
    raise FileNotFoundError(f"Algorithm path not found: {algo_path}")


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    """토큰 예산 초과 시 텍스트 앞부분만 남기고 자름 (4자 ≈ 1토큰)."""
    char_limit = max_tokens * 4
    if len(text) <= char_limit:
        return text
    return text[:char_limit] + f"\n... [truncated: {len(text) // 4 - max_tokens} tokens omitted]"


def build_prompt(origin_rtl_dir: Path, uarch_origin: Path | None, uarch_new: Path | None,
                 algo_origin: Path, algo_new: Path, graph_ctx_text: str = "",
                 input_token_budget: int = 60000) -> str:
    """
    input_token_budget: 전체 프롬프트 입력 토큰 상한.
    각 섹션을 예산 내에서 비례 배분해 truncate.
    """
    # 섹션별 대략적 배분: RTL 40%, algo 40%, graph 10%, uarch 10%
    rtl_budget    = int(input_token_budget * 0.40)
    algo_budget   = int(input_token_budget * 0.40)
    graph_budget  = int(input_token_budget * 0.10)
    uarch_budget  = int(input_token_budget * 0.10)

    prompt = []
    if graph_ctx_text:
        prompt.append(f"## Signal Causal Context (from Neo4j)\n{_truncate_to_tokens(graph_ctx_text, graph_budget)}\n")
    prompt += [
        "You are an RTL engineer. Generate a new Verilog module based on the deltas.",
        "=== Original RTL ===",
        _truncate_to_tokens(_read_rtl_sources(origin_rtl_dir), rtl_budget),
    ]
    if uarch_origin is not None:
        prompt += ["=== Micro-architecture (origin) ===", _truncate_to_tokens(uarch_origin.read_text(), uarch_budget // 2)]
    if uarch_new is not None:
        prompt += ["=== Micro-architecture (new) ===", _truncate_to_tokens(uarch_new.read_text(), uarch_budget // 2)]
    prompt += [
        "=== Algorithm (origin) ===",
        _truncate_to_tokens(_read_algo_sources(algo_origin, "Algorithm origin"), algo_budget // 2),
        "=== Algorithm (new) ===",
        _truncate_to_tokens(_read_algo_sources(algo_new, "Algorithm new"), algo_budget // 2),
        "=== Requirements ===",
        "- Keep the same module ports unless specification says otherwise.",
        "- Implement every behavioral delta described above (ROI gate, fractional timing, TE hold, etc.).",
        "- Output synthesizable SystemVerilog only (no Markdown fences, no commentary).",
        "- Ensure the module terminates with 'endmodule'.",
    ]
    return "\n".join(prompt)


def sanitize_verilog(text: str) -> str:
    clean = text.replace("```verilog", "").replace("```", "")
    idx = clean.find("module ")
    if idx != -1:
        clean = clean[idx:]
    return clean.strip()


def ensure_endmodule(content: str, cfg: dict, max_tokens: int = 1024) -> str:
    attempt = 0
    full = content
    while "endmodule" not in full and attempt < 3:
        cont_prompt = (
            "Continue the following Verilog module exactly where it stopped. "
            "Do not repeat prior lines; only provide the missing logic until the final 'endmodule'.\n"
            "=== Partial Module ===\n"
            f"{full}\n"
            "=== Continue ==="
        )
        extra = call_llm(
            cont_prompt,
            cfg,
            system_prompt="You complete partially-written Verilog modules. Return code only.",
            max_tokens=max_tokens,
        )
        full = f"{full}\n{sanitize_verilog(extra)}"
        attempt += 1
    return full


def build_prompt_chunked(
    origin_rtl_dir: Path,
    uarch_origin: Path | None,
    uarch_new: Path | None,
    algo_origin: Path,
    algo_new: Path,
    rtl_chunks_path: Path | None = None,
    pseudo_diff_path: Path | None = None,
    causal_graph_path: Path | None = None,
    token_budget: int = 6000,
    graph_ctx_text: str = "",
) -> tuple[str, bool]:
    """
    청크 기반 컨텍스트 선택 프롬프트 생성 시도.
    청크/diff 파일이 없으면 일반 build_prompt()로 폴백.

    반환: (prompt_str, chunked_mode_used: bool)
    """
    try:
        from context_selector import (  # type: ignore
            select_chunks, build_chunked_prompt, extract_diff_signals
        )

        if rtl_chunks_path is None or not rtl_chunks_path.exists():
            return build_prompt(origin_rtl_dir, uarch_origin, uarch_new, algo_origin, algo_new, graph_ctx_text=graph_ctx_text, input_token_budget=token_budget), False

        chunks = json.loads(rtl_chunks_path.read_text())

        diff_signals: set[str] = set()
        if pseudo_diff_path and pseudo_diff_path.exists():
            diff_obj = json.loads(pseudo_diff_path.read_text())
            diff_signals = extract_diff_signals(diff_obj.get('diff', []))

        causal_edges: list[dict] = []
        if causal_graph_path and causal_graph_path.exists():
            graph_obj = json.loads(causal_graph_path.read_text())
            causal_edges = graph_obj.get('graphs', [{}])[0].get('edges', [])

        selection = select_chunks(
            chunks, diff_signals, causal_edges, token_budget=token_budget
        )

        omit_count = len(selection.omitted)
        total = len(chunks)
        pct = int(100 * omit_count / total) if total else 0
        print(
            f"[codegen] chunked context: {total - omit_count}/{total} blocks selected "
            f"(~{selection.estimated_tokens} tokens, {pct}% omitted)"
        )

        prompt = build_chunked_prompt(
            selection, uarch_origin, uarch_new, algo_origin, algo_new
        )
        if graph_ctx_text:
            # token_budget의 10%를 graph context에 할당 (build_prompt()와 동일 비율)
            graph_budget = int(token_budget * 0.10)
            prompt = (
                f"## Signal Causal Context (from Neo4j)\n"
                f"{_truncate_to_tokens(graph_ctx_text, graph_budget)}\n\n"
                f"{prompt}"
            )
        return prompt, True

    except Exception as exc:
        warnings.warn(f"[codegen] chunked prompt failed ({exc}), falling back to full RTL", stacklevel=2)
        return build_prompt(origin_rtl_dir, uarch_origin, uarch_new, algo_origin, algo_new, graph_ctx_text=graph_ctx_text), False


def generate_rtl(cfg: dict, origin_rtl_dir: Path, uarch_origin: Path | None, uarch_new: Path | None, algo_origin: Path, algo_new: Path, output: Path) -> str:
    prompt = build_prompt(origin_rtl_dir, uarch_origin, uarch_new, algo_origin, algo_new)
    result = call_llm(prompt, cfg, system_prompt="You generate production-quality synthesizable Verilog.")
    clean = sanitize_verilog(result)
    clean = ensure_endmodule(clean, cfg, max_tokens=cfg.get("max_tokens", 1024))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(clean)
    return clean


def _build_retry_prompt(
    prev_rtl: str,
    verification: dict,
    origin_rtl_dir: Path,
    uarch_origin: Path | None,
    uarch_new: Path | None,
    algo_origin: Path,
    algo_new: Path,
    attempt: int,
) -> str:
    """검증 실패 결과를 피드백으로 포함한 재시도 프롬프트 생성."""
    results = verification.get("results", {})

    failure_lines: list[str] = []

    basic = results.get("basic", {})
    if basic.get("status") == "fail":
        failure_lines.append(f"- [basic] {basic.get('detail', 'unknown error')}")

    causal = results.get("causal", {})
    if causal.get("status") == "fail":
        failure_lines.append(f"- [causal] {causal.get('detail', 'unknown error')}")
        missing = causal.get("missing_edges", [])
        if missing:
            failure_lines.append("  The following causal signal dependencies are MISSING from the generated RTL:")
            for edge in missing:
                failure_lines.append(f"    * {edge}")
            failure_lines.append(
                "  Each missing edge means a signal that should drive another is not connected. "
                "Ensure every listed (driver → driven) relationship is explicitly implemented."
            )

    failures_text = "\n".join(failure_lines) if failure_lines else "- Unknown verification failure"

    prompt = [
        f"You are an RTL engineer. This is retry attempt #{attempt}.",
        "",
        "=== Previous RTL (FAILED verification) ===",
        prev_rtl,
        "",
        "=== Verification Failures ===",
        failures_text,
        "",
        "=== Original RTL ===",
        _read_rtl_sources(origin_rtl_dir),
    ]
    if uarch_origin is not None:
        prompt += ["=== Micro-architecture (origin) ===", uarch_origin.read_text()]
    if uarch_new is not None:
        prompt += ["=== Micro-architecture (new) ===", uarch_new.read_text()]
    prompt += [
        "=== Algorithm (origin) ===",
        _read_algo_sources(algo_origin, "Algorithm origin"),
        "=== Algorithm (new) ===",
        _read_algo_sources(algo_new, "Algorithm new"),
        "",
        "=== Requirements ===",
        "- Fix ALL verification failures listed above.",
        "- Keep the same module ports unless specification says otherwise.",
        "- Implement every behavioral delta described in the spec.",
        "- Output synthesizable Verilog only (no Markdown fences, no commentary).",
        "- Ensure the module terminates with 'endmodule'.",
    ]
    return "\n".join(prompt)


def _build_failure_section(verification: dict, attempt: int) -> str:
    """검증 실패 결과를 요약한 헤더 섹션 반환 (chunked retry용)."""
    results = verification.get("results", {})
    failure_lines: list[str] = [f"You are an RTL engineer. This is retry attempt #{attempt}.", ""]

    basic = results.get("basic", {})
    if basic.get("status") == "fail":
        failure_lines.append(f"=== Verification Failures ===")
        failure_lines.append(f"- [basic] {basic.get('detail', 'unknown error')}")

    causal = results.get("causal", {})
    if causal.get("status") == "fail":
        if "=== Verification Failures ===" not in failure_lines:
            failure_lines.append("=== Verification Failures ===")
        failure_lines.append(f"- [causal] {causal.get('detail', 'unknown error')}")
        missing = causal.get("missing_edges", [])
        if missing:
            failure_lines.append("  The following causal signal dependencies are MISSING:")
            for edge in missing:
                failure_lines.append(f"    * {edge}")
            failure_lines.append(
                "  Ensure every listed (driver → driven) relationship is explicitly implemented."
            )

    if len(failure_lines) <= 2:
        failure_lines += ["=== Verification Failures ===", "- Unknown verification failure"]

    failure_lines += ["", "Fix ALL verification failures listed above.", ""]
    return "\n".join(failure_lines)


def generate_rtl_with_retry(
    cfg: dict,
    origin_rtl_dir: Path,
    uarch_origin: Path | None,
    uarch_new: Path | None,
    algo_origin: Path,
    algo_new: Path,
    output: Path,
    causal_graph_path: Path | None = None,
    max_retries: int = 2,
    rtl_chunks_path: Path | None = None,
    pseudo_diff_path: Path | None = None,
    token_budget: int = 6000,
    graph_ctx_text: str = "",
    output_max_tokens: int | None = None,
) -> tuple[str, dict]:
    """
    RTL을 생성하고 검증을 실행한다.
    검증 실패 시 실패 이유를 피드백으로 포함해 최대 max_retries회 재시도한다.

    output_max_tokens: RTL 생성에 사용할 출력 토큰 수.
      None이면 cfg["max_tokens"]를 그대로 사용 (yaml 설정 우선).
      명시하면 yaml 설정보다 우선 적용.

    반환: (최종 RTL 문자열, 최종 verification dict)
    """
    # 지연 import — orchestrator/ 내에서만 사용
    from verify import run_checks  # type: ignore

    # output_max_tokens가 None이면 yaml cfg 값 사용 (예: max_tokens: 65536)
    effective_output_tokens = output_max_tokens if output_max_tokens is not None else cfg.get("max_tokens", 8192)
    # 입력 예산 = token_budget (flow.py에서 safe_input_token_budget으로 계산된 값)
    input_budget = token_budget

    attempt = 0
    current_rtl: str = ""
    verification: dict = {}

    while attempt <= max_retries:
        if attempt == 0:
            prompt, chunked = build_prompt_chunked(
                origin_rtl_dir, uarch_origin, uarch_new, algo_origin, algo_new,
                rtl_chunks_path=rtl_chunks_path,
                pseudo_diff_path=pseudo_diff_path,
                causal_graph_path=causal_graph_path,
                token_budget=input_budget,
                graph_ctx_text=graph_ctx_text,
            )
            system = "You generate production-quality synthesizable Verilog."
            if chunked:
                system += " For any omitted block, reproduce it exactly as-is from origin."
        else:
            # 재시도: chunked 방식으로 관련 청크만 + 실패 피드백 주입
            try:
                base_prompt, chunked = build_prompt_chunked(
                    origin_rtl_dir, uarch_origin, uarch_new, algo_origin, algo_new,
                    rtl_chunks_path=rtl_chunks_path,
                    pseudo_diff_path=pseudo_diff_path,
                    causal_graph_path=causal_graph_path,
                    token_budget=input_budget,
                    graph_ctx_text=graph_ctx_text,
                )
                failure_header = _build_failure_section(verification, attempt)
                prompt = f"{failure_header}\n{base_prompt}"
            except Exception:
                prompt = _build_retry_prompt(
                    current_rtl, verification,
                    origin_rtl_dir, uarch_origin, uarch_new, algo_origin, algo_new,
                    attempt,
                )
                chunked = False
            system = (
                "You are an RTL engineer fixing a Verilog module that failed automated verification. "
                "Address every listed failure. Return corrected Verilog code only."
            )
            if chunked:
                system += " For any omitted block, reproduce it exactly as-is from origin."

        result = call_llm(prompt, cfg, system_prompt=system, max_tokens=effective_output_tokens)
        current_rtl = sanitize_verilog(result)
        current_rtl = ensure_endmodule(current_rtl, cfg, max_tokens=effective_output_tokens)

        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(current_rtl)

        verification = run_checks(output, causal_graph_path=causal_graph_path, causal_threshold=cfg.get("verify_causal_threshold", 0.5))
        status = verification["status"]

        print(f"[codegen] attempt {attempt + 1}/{max_retries + 1} → {status}")

        if status == "pass":
            break

        if attempt < max_retries:
            failed_details = [
                f"  [{name}] {res.get('detail', '')} {res.get('missing_edges', [])}"
                for name, res in verification["results"].items()
                if res.get("status") == "fail"
            ]
            print("[codegen] verification failed, retrying with feedback:")
            for line in failed_details:
                print(line)
        else:
            warnings.warn(
                f"[codegen] RTL generation failed verification after {max_retries + 1} attempts. "
                "Saving last attempt as output.",
                stacklevel=2,
            )

        attempt += 1

    return current_rtl, verification


# ─────────────────────────────────────────────────────────────
# Patch Mode: 변경 블록만 LLM 생성 후 원본에 병합
# ─────────────────────────────────────────────────────────────

def _block_is_complete(block_text: str) -> bool:
    """
    블록이 완전히 닫혔는지 확인.
    begin/end 카운트 또는 assign 단일 라인 여부로 판단.
    """
    stripped = block_text.strip()
    # assign은 세미콜론으로 끝나면 완전
    if stripped.startswith("assign"):
        return stripped.rstrip().endswith(";")
    # always/if 블록: begin/end 균형 확인
    begins = stripped.count("begin")
    ends = len([t for t in stripped.split() if t in ("end", "endcase")])
    return begins > 0 and ends >= begins


def _count_begin_end_depth(text: str) -> int:
    """
    텍스트에서 begin/end 깊이를 계산.
    양수 = begin이 더 많음 (블록 미완성), 0 = 균형, 음수 = end 과잉
    case/endcase, function/endfunction도 함께 처리.
    """
    depth = 0
    # 주석 제거 후 검사
    clean = re.sub(r"//[^\n]*", "", text)
    clean = re.sub(r"/\*.*?\*/", " ", clean, flags=re.DOTALL)
    for tok in re.findall(r"\b(\w+)\b", clean):
        if tok in ("begin", "case", "casex", "casez", "function", "task"):
            depth += 1
        elif tok in ("end", "endcase", "endfunction", "endtask"):
            depth -= 1
    return depth


def _collect_related_chunks(
    block: dict,
    all_chunks: list[dict],
    block_idx: int,
    causal_edges: list[dict],
) -> list[dict]:
    """
    현재 블록과 관련된 추가 청크를 수집.

    수집 기준:
    1. begin/end 미완성 → next chunk(들) 자동 포함 (깊이가 0이 될 때까지)
    2. 이 블록이 참조하는 신호의 decl/localparam 청크
    3. causal graph 기준 1-hop 연관 신호를 lhs로 가진 다른 always/assign 청크
    4. 같은 신호를 lhs로 가진 다른 always 청크 (다중 always 분리 패턴)

    반환: 추가 컨텍스트로 포함할 청크 목록 (block 자신은 제외)
    """
    related: list[dict] = []
    seen_ids: set[int] = {id(block)}

    block_signals: set[str] = set(block.get("signals", []))
    block_lhs: set[str] = set(block.get("lhs", []))

    # ── 1. begin/end 완전성 검사 → next chunk 자동 포함 ──────────────────
    accumulated_text = block.get("text", "")
    depth = _count_begin_end_depth(accumulated_text)
    next_idx = block_idx + 1
    while depth > 0 and next_idx < len(all_chunks):
        next_chunk = all_chunks[next_idx]
        accumulated_text += "\n" + next_chunk.get("text", "")
        depth = _count_begin_end_depth(accumulated_text)
        if id(next_chunk) not in seen_ids:
            related.append(next_chunk)
            seen_ids.add(id(next_chunk))
            print(f"    [related] begin/end 미완성 → next chunk 포함: "
                  f"L{next_chunk.get('line_start')}-{next_chunk.get('line_end')} "
                  f"kind={next_chunk.get('kind')}")
        next_idx += 1
        if next_idx - block_idx > 5:  # 최대 5개 청크까지만 추가
            break

    # ── 2. block 참조 신호의 decl/localparam 청크 ─────────────────────────
    for chunk in all_chunks:
        if id(chunk) in seen_ids:
            continue
        kind = chunk.get("kind", "")
        if kind not in ("decl", "localparam"):
            continue
        chunk_signals: set[str] = set(chunk.get("signals", []))
        if chunk_signals & block_signals:
            related.append(chunk)
            seen_ids.add(id(chunk))

    # ── 3. causal 1-hop 연관 신호를 lhs로 가진 always/assign 청크 ──────────
    # block_signals 기준으로 causal edge 확장
    causal_related: set[str] = set()
    for edge in causal_edges:
        frm, to = edge.get("from", ""), edge.get("to", "")
        if frm in block_signals or to in block_signals:
            causal_related.add(frm)
            causal_related.add(to)

    for chunk in all_chunks:
        if id(chunk) in seen_ids:
            continue
        if chunk.get("kind") not in ("always", "assign", "comb", "clocked"):
            continue
        chunk_lhs: set[str] = set(chunk.get("lhs", []))
        if chunk_lhs & causal_related:
            related.append(chunk)
            seen_ids.add(id(chunk))
            print(f"    [related] causal 연관 → chunk 포함: "
                  f"L{chunk.get('line_start')}-{chunk.get('line_end')} "
                  f"lhs={list(chunk_lhs)[:3]}")

    # ── 4. 같은 lhs 신호를 가진 다른 always 청크 (분리 always 패턴) ─────────
    for chunk in all_chunks:
        if id(chunk) in seen_ids:
            continue
        if chunk.get("kind") not in ("always", "assign"):
            continue
        chunk_lhs2: set[str] = set(chunk.get("lhs", []))
        if chunk_lhs2 & block_lhs:
            related.append(chunk)
            seen_ids.add(id(chunk))
            print(f"    [related] 동일 lhs 신호 → chunk 포함: "
                  f"L{chunk.get('line_start')}-{chunk.get('line_end')} "
                  f"lhs={list(chunk_lhs2)[:3]}")

    return related


def _build_block_prompt(
    block_text: str,
    block_signals: list[str],
    algo_origin: Path,
    algo_new: Path,
    uarch_new: Path | None,
    graph_ctx_text: str,
    pseudo_diff_text: str,
    cfg: dict,
    related_chunks: list[dict] | None = None,
) -> str:
    """
    변경이 필요한 단일 블록에 대한 LLM 프롬프트 생성.
    related_chunks: 연관 컨텍스트 청크 (decl, causal 연관 블록 등)
    """
    block_tokens = min(max(len(block_text) // 4 * 2 + 512, 1024), cfg.get("max_tokens", 8192))
    # 블록 재작성용 입력 예산: 최대 6000토큰 하드캡
    input_budget = min(cfg.get("block_input_budget", 6000), 6000)

    # related_chunks 토큰 예산 확보: 최대 15% 할당
    related_budget = int(input_budget * 0.15) if related_chunks else 0
    remaining = input_budget - related_budget

    # 섹션별 토큰 배분: algo 50%, graph 18%, uarch 17%, diff 10%, related 15%
    algo_budget   = int(remaining * 0.53)
    graph_budget  = int(remaining * 0.19)
    uarch_budget  = int(remaining * 0.18)
    diff_budget   = int(remaining * 0.10)

    parts = [
        "Rewrite the following Verilog block based on the spec changes.",
        "Return ONLY the rewritten block code. No module wrapper, no markdown fences.",
        "",
        "=== Original Block ===",
        block_text,
    ]

    # 연관 컨텍스트 청크 (decl + causal 연관)
    if related_chunks:
        related_texts: list[str] = []
        used_tokens = 0
        per_chunk_max = max(related_budget // max(len(related_chunks), 1), 80)
        for rc in related_chunks:
            rc_text = rc.get("text", "")
            rc_tokens = len(rc_text) // 4
            if used_tokens + rc_tokens > related_budget:
                rc_text = _truncate_to_tokens(rc_text, per_chunk_max)
            related_texts.append(
                f"// [{rc.get('kind','?')}] L{rc.get('line_start')}-{rc.get('line_end')}\n{rc_text}"
            )
            used_tokens += len(rc_text) // 4
        parts += [
            "",
            "=== Related Context (declarations & connected blocks) ===",
            "\n\n".join(related_texts),
        ]

    if graph_ctx_text:
        parts += ["", "=== Signal Causal Context ===", _truncate_to_tokens(graph_ctx_text, graph_budget)]
    if pseudo_diff_text:
        parts += ["", "=== Spec Delta (pseudo-diff) ===", _truncate_to_tokens(pseudo_diff_text, diff_budget)]
    if uarch_new and uarch_new.exists():
        parts += ["", "=== Micro-architecture (new) ===", _truncate_to_tokens(uarch_new.read_text(), uarch_budget)]
    parts += [
        "",
        "=== Algorithm (new) ===",
        _truncate_to_tokens(_read_algo_sources(algo_new, "Algorithm new"), algo_budget),
        "",
        "=== Requirements ===",
        f"- Signals in this block: {', '.join(block_signals)}",
        "- Apply ALL behavioral changes from the spec delta.",
        "- Keep port names and signal widths unchanged unless spec says otherwise.",
        "- Return only the rewritten block (always/assign). No module/endmodule.",
    ]
    return "\n".join(parts)


# diff_signals 중 RTL 신호가 아닌 Python/prose 식별자를 걸러내는 패턴
_NON_RTL_SIGNAL_RE = re.compile(
    r"^(algorithm|algorithm_new|algorithm_origin|origin|new|the|must|have|same|"
    r"typing|py|src|src_x|out_frame|out_line|in_line|in_crop|avg|checksum|flat|"
    r"frame|pix|row|rows|height|width|sat_mul2_u8|clip_u8|new_tcon_model|"
    r"original_tcon_model|dim_active_list|line_avg|line_checksum|line_flat|p|v|x|y)$"
)
# RTL 신호명 heuristic: snake_case, 길이≥3, 숫자로 시작 안 함, 단일 알파벳 아님
def _looks_like_rtl_signal(name: str) -> bool:
    if len(name) <= 1:
        return False
    if _NON_RTL_SIGNAL_RE.match(name):
        return False
    # 순수 숫자나 단일 문자는 제외
    if name.isdigit():
        return False
    return True


def _extract_origin_signals(chunks: list[dict]) -> set[str]:
    """
    origin chunks에서 이미 선언된 신호 이름 집합을 추출.
    header(port), decl(wire/reg), localparam 모두 포함.
    """
    known: set[str] = set()
    port_re = re.compile(
        r"(input|output|inout)\s+(?:wire|reg|logic|signed|unsigned)?\s*(?:\[[^\]]*\]\s*)?(\w+)"
    )
    decl_re = re.compile(r"\b(logic|wire|reg|integer)\s*(?:\[[^\]]*\])?\s*(\w+)")
    param_re = re.compile(r"\b(parameter|localparam)\s+(\w+)")
    for chunk in chunks:
        text = chunk.get("text", "")
        for _, name in port_re.findall(text):
            known.add(name)
        for _, name in decl_re.findall(text):
            known.add(name)
        for _, name in param_re.findall(text):
            known.add(name)
    return known


def _build_header_patch_prompt(
    header_text: str,
    pseudo_diff_text: str,
    uarch_new: Path | None,
    algo_new: Path,
    cfg: dict,
) -> str:
    """
    모듈 header(port list) 재작성 프롬프트.
    새 포트 추가만 수행하고 기존 포트는 그대로 유지.
    """
    input_budget = min(cfg.get("block_input_budget", 6000), 6000)
    parts = [
        "Rewrite the following Verilog module header (port list only).",
        "ADD any new ports required by the spec delta. Keep ALL existing ports unchanged.",
        "Return ONLY the rewritten header text (from 'module' up to and including ');'). No body, no markdown.",
        "",
        "=== Original Header ===",
        header_text,
    ]
    if pseudo_diff_text:
        parts += ["", "=== Spec Delta (pseudo-diff) ===",
                  _truncate_to_tokens(pseudo_diff_text, int(input_budget * 0.15))]
    if uarch_new and uarch_new.exists():
        parts += ["", "=== Micro-architecture (new) ===",
                  _truncate_to_tokens(uarch_new.read_text(), int(input_budget * 0.25))]
    parts += [
        "", "=== Algorithm (new) ===",
        _truncate_to_tokens(_read_algo_sources(algo_new, "Algorithm new"), int(input_budget * 0.50)),
        "",
        "=== Requirements ===",
        "- Keep all existing ports exactly as-is (name, direction, width).",
        "- Add new input/output ports required by the spec.",
        "- Match bit widths from the spec (e.g. [7:0] for 8-bit signals).",
        "- Return only the header (module ... );  — no body, no endmodule.",
    ]
    return "\n".join(parts)


def _build_decl_patch_prompt(
    existing_decls: str,
    new_signals_hint: list[str],
    pseudo_diff_text: str,
    uarch_new: Path | None,
    algo_new: Path,
    cfg: dict,
) -> str:
    """
    내부 신호 선언(wire/reg) 추가 프롬프트.
    new_signals_hint: spec에서 추론된 신규 신호 이름 목록
    """
    input_budget = min(cfg.get("block_input_budget", 6000), 6000)
    parts = [
        "Generate additional Verilog internal signal declarations (wire/reg) required by the spec.",
        "Return ONLY the new declaration lines (one per line). Do NOT repeat existing declarations.",
        "",
        "=== Existing Declarations ===",
        existing_decls,
        "",
        f"=== Likely New Signals (from spec) ===",
        ", ".join(new_signals_hint) if new_signals_hint else "(derive from spec delta)",
    ]
    if pseudo_diff_text:
        parts += ["", "=== Spec Delta (pseudo-diff) ===",
                  _truncate_to_tokens(pseudo_diff_text, int(input_budget * 0.15))]
    if uarch_new and uarch_new.exists():
        parts += ["", "=== Micro-architecture (new) ===",
                  _truncate_to_tokens(uarch_new.read_text(), int(input_budget * 0.25))]
    parts += [
        "", "=== Algorithm (new) ===",
        _truncate_to_tokens(_read_algo_sources(algo_new, "Algorithm new"), int(input_budget * 0.45)),
        "",
        "=== Requirements ===",
        "- Only output NEW declaration lines not already in existing declarations.",
        "- Use wire/reg with correct bit widths from spec.",
        "- One declaration per line, terminated with semicolon.",
        "- No module wrapper, no markdown, no comments.",
    ]
    return "\n".join(parts)


def _insert_decls_into_rtl(rtl_text: str, new_decl_text: str, header_end_marker: str = ");") -> str:
    """
    새 신호 선언을 RTL 텍스트의 header(');') 바로 뒤에 삽입.
    """
    new_lines = [l for l in new_decl_text.strip().splitlines() if l.strip()]
    if not new_lines:
        return rtl_text

    # ');' 이후 첫 번째 빈 줄 또는 localparam/reg 선언 직전에 삽입
    lines = rtl_text.splitlines(keepends=True)
    insert_pos = None
    in_header = False
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped == ");":
            in_header = False
            insert_pos = idx + 1
            break

    if insert_pos is None:
        # fallback: endmodule 바로 전에 삽입
        for idx in range(len(lines) - 1, -1, -1):
            if "endmodule" in lines[idx]:
                insert_pos = idx
                break

    if insert_pos is None:
        return rtl_text + "\n" + "\n".join(new_lines) + "\n"

    insertion = "\n// [patch: new signal declarations]\n" + "\n".join(new_lines) + "\n"
    lines.insert(insert_pos, insertion)
    return "".join(lines)


def generate_rtl_patch_mode(
    cfg: dict,
    origin_rtl_dir: Path,
    uarch_origin: Path | None,
    uarch_new: Path | None,
    algo_origin: Path,
    algo_new: Path,
    output: Path,
    causal_graph_path: Path | None = None,
    rtl_chunks_path: Path | None = None,
    pseudo_diff_path: Path | None = None,
    graph_ctx_text: str = "",
    max_retries: int = 1,
) -> tuple[str, dict]:
    """
    Patch Mode RTL 생성:
    1. [NEW] header(port list) 재작성 → 새 포트 추가
    2. [NEW] decl(wire/reg) 보강 → 새 내부 신호 삽입
    3. logic block(always/assign) rewrite → 파이프라인 로직 변경
    4. apply_patch()로 원본에 병합
    rtl_chunks_path가 없으면 generate_rtl_with_retry()로 자동 fallback.

    반환: (최종 RTL 문자열, verification dict)
    """
    import re as _re
    import time as _time
    from verify import run_checks  # type: ignore

    # chunks 없으면 fallback
    if rtl_chunks_path is None or not rtl_chunks_path.exists():
        warnings.warn("[codegen/patch] rtl_chunks_path 없음 → 일반 모드로 fallback", stacklevel=2)
        return generate_rtl_with_retry(
            cfg, origin_rtl_dir, uarch_origin, uarch_new, algo_origin, algo_new,
            output, causal_graph_path=causal_graph_path,
            rtl_chunks_path=None, pseudo_diff_path=pseudo_diff_path,
            graph_ctx_text=graph_ctx_text,
        )

    # 스크립트 경로 추가
    scripts_dir = Path(__file__).parent.parent / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

    from context_selector import select_chunks, extract_diff_signals  # type: ignore
    from patch_rtl import apply_patch  # type: ignore

    chunks = json.loads(rtl_chunks_path.read_text())

    # diff signals 추출
    raw_diff_signals: set[str] = set()
    pseudo_diff_text = ""
    if pseudo_diff_path and pseudo_diff_path.exists():
        diff_obj = json.loads(pseudo_diff_path.read_text())
        raw_diff_signals = extract_diff_signals(diff_obj.get("diff", []))
        pseudo_diff_text = "\n".join(diff_obj.get("diff", []))

    # origin에 이미 있는 신호를 제외 + RTL 식별자 heuristic 필터 → 진짜 신규 신호만 남김
    origin_known_signals = _extract_origin_signals(chunks)
    diff_signals = {s for s in (raw_diff_signals - origin_known_signals)
                    if _looks_like_rtl_signal(s)}
    new_signals_hint = sorted(diff_signals)

    print(f"[codegen/patch] raw diff_signals={len(raw_diff_signals)}, "
          f"after filtering origin={len(diff_signals)}: {new_signals_hint[:8]}")

    # causal edges
    causal_edges: list[dict] = []
    if causal_graph_path and causal_graph_path.exists():
        graph_obj = json.loads(causal_graph_path.read_text())
        causal_edges = graph_obj.get("graphs", [{}])[0].get("edges", [])

    # 원본 RTL 읽기
    origin_rtl_text = _read_rtl_sources(origin_rtl_dir)
    _req_interval = cfg.get("req_interval", 1.0)
    cfg_max = cfg.get("max_tokens", 8192)

    patches: list[dict] = []

    # ─────────────────────────────────────────────────────
    # Step 0: header(port list) 재작성 → 새 포트 추가
    # ─────────────────────────────────────────────────────
    header_chunks = [c for c in chunks if c.get("kind") == "header"]
    if header_chunks:
        header_chunk = header_chunks[0]
        header_text = header_chunk.get("text", "")
        print("[codegen/patch] Step 0: header(port list) 재작성")
        header_prompt = _build_header_patch_prompt(
            header_text, pseudo_diff_text, uarch_new, algo_new, cfg
        )
        try:
            header_result = call_llm(
                header_prompt, cfg,
                system_prompt=(
                    "You are an RTL engineer updating a Verilog module header. "
                    "Add new ports from the spec. Keep existing ports unchanged. "
                    "Return only the header (module...); — no body, no endmodule, no markdown."
                ),
                max_tokens=min(cfg_max, max(len(header_text) // 4 * 3 + 512, 1024)),
            )
            if header_result:
                header_result = header_result.replace("```verilog", "").replace("```", "").strip()
                # header가 ');'로 끝나는지 확인
                if ");" in header_result:
                    patches.append({
                        "original": header_text,
                        "replacement": header_result,
                        "chunk": header_chunk,
                    })
                    print(f"[codegen/patch] header patch 준비 완료 "
                          f"({len(header_text.splitlines())}→{len(header_result.splitlines())} lines)")
                else:
                    warnings.warn("[codegen/patch] header 결과가 ');'로 끝나지 않음 — 원본 유지", stacklevel=2)
        except Exception as exc:
            warnings.warn(f"[codegen/patch] header 재작성 실패: {exc} — 원본 유지", stacklevel=2)
        _time.sleep(_req_interval)
    else:
        warnings.warn("[codegen/patch] header chunk 없음 — 포트 추가 스킵", stacklevel=2)

    # ─────────────────────────────────────────────────────
    # Step 0.5: 새 내부 신호 선언(decl) 추가
    # ─────────────────────────────────────────────────────
    if new_signals_hint:
        decl_chunks = [c for c in chunks if c.get("kind") == "decl"]
        existing_decls = "\n".join(c.get("text", "") for c in decl_chunks)
        print(f"[codegen/patch] Step 0.5: 신규 내부 신호 선언 추가 (hints: {new_signals_hint[:6]})")
        decl_prompt = _build_decl_patch_prompt(
            existing_decls, new_signals_hint, pseudo_diff_text, uarch_new, algo_new, cfg
        )
        try:
            decl_result = call_llm(
                decl_prompt, cfg,
                system_prompt=(
                    "You are an RTL engineer. Generate ONLY new wire/reg declaration lines "
                    "that are missing from the existing declarations. "
                    "Return one declaration per line. No module, no markdown."
                ),
                max_tokens=min(cfg_max, 512),
            )
            if decl_result:
                decl_result = decl_result.replace("```verilog", "").replace("```", "").strip()
                # 빈 결과 또는 "none" 류 응답 필터
                decl_lines = [l for l in decl_result.splitlines()
                               if l.strip() and "none" not in l.lower()
                               and not l.strip().startswith("//")]
                if decl_lines:
                    print(f"[codegen/patch] 추가 선언 {len(decl_lines)}개: {decl_lines[:3]}")
                    # patch list에 직접 넣지 않고 RTL text에 삽입 (insert_pos 기반)
                    # apply_patch() 이후에 적용하기 위해 별도 보관
                    _new_decl_lines = "\n".join(decl_lines)
                else:
                    _new_decl_lines = ""
                    print("[codegen/patch] 추가 선언 없음 (LLM이 불필요 판단)")
            else:
                _new_decl_lines = ""
        except Exception as exc:
            warnings.warn(f"[codegen/patch] 신호 선언 추가 실패: {exc}", stacklevel=2)
            _new_decl_lines = ""
        _time.sleep(_req_interval)
    else:
        _new_decl_lines = ""
        print("[codegen/patch] Step 0.5: 신규 신호 없음 — 선언 추가 스킵")

    # ─────────────────────────────────────────────────────
    # Step 1: logic block(always/assign) rewrite
    # 변경 대상: diff_signals(신규) + origin에 있지만 로직 변경이 필요한 신호
    # ─────────────────────────────────────────────────────
    all_logic_blocks = [
        c for c in chunks
        if c.get("kind") in ("always", "assign", "comb", "clocked")
    ]

    # 신규 신호 관련 블록 + spec 변경으로 로직이 바뀌어야 하는 블록 선정
    # "spec 변경 영향권" = raw_diff_signals (필터 전) 기반으로 넓게 잡음
    target_blocks = [
        c for c in all_logic_blocks
        if set(c.get("signals", [])) & raw_diff_signals
        or set(c.get("lhs", [])) & raw_diff_signals
        or set(c.get("signals", [])) & diff_signals
        or set(c.get("lhs", [])) & diff_signals
    ]
    if not target_blocks:
        warnings.warn("[codegen/patch] diff_signals 매칭 없음 → 전체 로직 블록 대상으로 확장", stacklevel=2)
        target_blocks = all_logic_blocks

    print(f"[codegen/patch] Step 1: logic block rewrite {len(target_blocks)}개 / 전체 {len(chunks)}개")

    # chunks 전체 리스트에서 target_blocks의 인덱스 사전 구축
    chunk_index_map: dict[int, int] = {id(c): idx for idx, c in enumerate(chunks)}

    for i, block in enumerate(target_blocks):
        if i > 0:
            _time.sleep(_req_interval)

        block_text = block.get("text", "")
        block_signals = list(set(block.get("signals", [])) | set(block.get("lhs", [])))
        block_tokens = min(
            max(len(block_text) // 4 * 3 + 512, cfg_max),
            cfg_max * 2,
        )

        # 연관 청크 수집 (begin/end 완전성 + causal + 동일 lhs)
        block_pos_in_chunks = chunk_index_map.get(id(block), 0)
        related = _collect_related_chunks(block, chunks, block_pos_in_chunks, causal_edges)
        if related:
            related_summary = ", ".join(
                "L{}-{}({})".format(c.get("line_start"), c.get("line_end"), c.get("kind"))
                for c in related[:4]
            )
            print(f"  → related chunks {len(related)}개: {related_summary}")

        print(f"[codegen/patch] 블록 {i+1}/{len(target_blocks)}: "
              f"L{block.get('line_start')}-{block.get('line_end')} "
              f"signals={block_signals[:3]} (~{len(block_text)//4} tokens)")

        prompt = _build_block_prompt(
            block_text, block_signals,
            algo_origin, algo_new, uarch_new,
            graph_ctx_text, pseudo_diff_text, cfg,
            related_chunks=related if related else None,
        )

        for attempt in range(max_retries + 1):
            try:
                chunk_max = min(block_tokens, cfg.get("max_tokens", 8192))
                result = call_llm(
                    prompt, cfg,
                    system_prompt="You rewrite a single Verilog always/assign block. Return the block code only, no module wrapper, no markdown.",
                    max_tokens=chunk_max,
                )
                if not result:
                    raise ValueError("LLM returned empty/None response")
                result = result.replace("```verilog", "").replace("```", "").strip()

                # finish_reason=length 대응
                cont_attempts = 0
                while cont_attempts < 3 and result and not _block_is_complete(result):
                    cont_prompt = (
                        "Continue the following Verilog block exactly where it stopped. "
                        "Do not repeat prior lines. Return only the missing part until the block closes (end/endmodule excluded).\n"
                        f"=== Partial Block ===\n{result}\n=== Continue ==="
                    )
                    extra = call_llm(
                        cont_prompt, cfg,
                        system_prompt="You complete partially-written Verilog blocks. Return code only.",
                        max_tokens=chunk_max,
                    )
                    if extra:
                        result = result + "\n" + extra.replace("```verilog", "").replace("```", "").strip()
                    cont_attempts += 1

                if result:
                    patches.append({"original": block_text, "replacement": result, "chunk": block})
                    break
            except Exception as exc:
                if attempt < max_retries:
                    warnings.warn(f"[codegen/patch] 블록 {i+1} 재시도 ({exc})", stacklevel=2)
                else:
                    warnings.warn(f"[codegen/patch] 블록 {i+1} 실패, 원본 유지: {exc}", stacklevel=2)

    # ─────────────────────────────────────────────────────
    # Step 2: 패치 적용
    # ─────────────────────────────────────────────────────
    patched_rtl = apply_patch(origin_rtl_text, patches)

    # Step 2.5: 새 내부 신호 선언 삽입 (header ');' 직후)
    if _new_decl_lines:
        patched_rtl = _insert_decls_into_rtl(patched_rtl, _new_decl_lines)
        print(f"[codegen/patch] 내부 신호 선언 삽입 완료")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(patched_rtl)

    verification = run_checks(output, causal_graph_path=causal_graph_path,
                              causal_threshold=cfg.get("verify_causal_threshold", 0.5))
    print(f"[codegen/patch] 검증 결과: {verification['status']}")

    return patched_rtl, verification
