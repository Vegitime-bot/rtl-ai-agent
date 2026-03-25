from __future__ import annotations

import json
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
            prompt = f"## Signal Causal Context (from Neo4j)\n{graph_ctx_text}\n\n{prompt}"
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

        verification = run_checks(output, causal_graph_path=causal_graph_path)
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

def _build_block_prompt(
    block_text: str,
    block_signals: list[str],
    algo_origin: Path,
    algo_new: Path,
    uarch_new: Path | None,
    graph_ctx_text: str,
    pseudo_diff_text: str,
    cfg: dict,
) -> str:
    """변경이 필요한 단일 블록에 대한 LLM 프롬프트 생성."""
    parts = [
        "Rewrite the following Verilog block based on the spec changes.",
        "Return ONLY the rewritten block code. No module wrapper, no markdown fences.",
        "",
        "=== Original Block ===",
        block_text,
    ]
    if graph_ctx_text:
        parts += ["", "=== Signal Causal Context ===", graph_ctx_text]
    if pseudo_diff_text:
        parts += ["", "=== Spec Delta (pseudo-diff) ===", pseudo_diff_text[:4000]]
    if uarch_new and uarch_new.exists():
        parts += ["", "=== Micro-architecture (new) ===", _truncate_to_tokens(uarch_new.read_text(), 2000)]
    parts += [
        "",
        "=== Algorithm (new) ===",
        _truncate_to_tokens(_read_algo_sources(algo_new, "Algorithm new"), 4000),
        "",
        "=== Requirements ===",
        f"- Signals in this block: {', '.join(block_signals)}",
        "- Apply ALL behavioral changes from the spec delta.",
        "- Keep port names and signal widths unchanged unless spec says otherwise.",
        "- Return only the rewritten block (always/assign). No module/endmodule.",
    ]
    return "\n".join(parts)


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
    변경이 필요한 블록만 LLM으로 생성 후 원본 RTL에 병합.
    rtl_chunks_path가 없으면 generate_rtl_with_retry()로 자동 fallback.

    반환: (최종 RTL 문자열, verification dict)
    """
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
    from patch_rtl import find_block, apply_patch  # type: ignore

    chunks = json.loads(rtl_chunks_path.read_text())

    # diff signals 추출
    diff_signals: set[str] = set()
    pseudo_diff_text = ""
    if pseudo_diff_path and pseudo_diff_path.exists():
        diff_obj = json.loads(pseudo_diff_path.read_text())
        diff_signals = extract_diff_signals(diff_obj.get("diff", []))
        pseudo_diff_text = "\n".join(diff_obj.get("diff", []))

    # causal edges
    causal_edges: list[dict] = []
    if causal_graph_path and causal_graph_path.exists():
        graph_obj = json.loads(causal_graph_path.read_text())
        causal_edges = graph_obj.get("graphs", [{}])[0].get("edges", [])

    # 변경 필요 블록 선택
    selection = select_chunks(chunks, diff_signals, causal_edges, token_budget=999999)
    target_blocks = [
        c for c in selection.must_include
        if c.get("kind") in ("always", "assign", "comb", "clocked")
        and (set(c.get("signals", [])) & diff_signals or set(c.get("lhs", [])) & diff_signals)
    ]

    if not target_blocks:
        warnings.warn("[codegen/patch] 변경 대상 블록 없음 → 일반 모드로 fallback", stacklevel=2)
        return generate_rtl_with_retry(
            cfg, origin_rtl_dir, uarch_origin, uarch_new, algo_origin, algo_new,
            output, causal_graph_path=causal_graph_path,
            rtl_chunks_path=rtl_chunks_path, pseudo_diff_path=pseudo_diff_path,
            graph_ctx_text=graph_ctx_text,
        )

    print(f"[codegen/patch] 변경 대상 블록: {len(target_blocks)}개 / 전체 {len(chunks)}개")

    # 원본 RTL 읽기
    origin_rtl_text = _read_rtl_sources(origin_rtl_dir)

    patches: list[dict] = []
    for i, block in enumerate(target_blocks):
        block_text = block.get("text", "")
        block_signals = list(set(block.get("signals", [])) | set(block.get("lhs", [])))
        block_tokens = max(len(block_text) // 4 * 2, 2048)

        print(f"[codegen/patch] 블록 {i+1}/{len(target_blocks)}: "
              f"L{block.get('line_start')}-{block.get('line_end')} "
              f"signals={block_signals[:3]} (~{len(block_text)//4} tokens)")

        prompt = _build_block_prompt(
            block_text, block_signals,
            algo_origin, algo_new, uarch_new,
            graph_ctx_text, pseudo_diff_text, cfg,
        )

        for attempt in range(max_retries + 1):
            try:
                result = call_llm(
                    prompt, cfg,
                    system_prompt="You rewrite a single Verilog always/assign block. Return the block code only, no module wrapper, no markdown.",
                    max_tokens=min(block_tokens, cfg.get("max_tokens", 8192)),
                )
                result = result.replace("```verilog", "").replace("```", "").strip()
                if result:
                    patches.append({"original": block_text, "replacement": result})
                    break
            except Exception as exc:
                if attempt < max_retries:
                    warnings.warn(f"[codegen/patch] 블록 {i+1} 재시도 ({exc})", stacklevel=2)
                else:
                    warnings.warn(f"[codegen/patch] 블록 {i+1} 실패, 원본 유지: {exc}", stacklevel=2)

    # 원본에 패치 적용
    patched_rtl = apply_patch(origin_rtl_text, patches)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(patched_rtl)

    verification = run_checks(output, causal_graph_path=causal_graph_path)
    print(f"[codegen/patch] 검증 결과: {verification['status']}")

    return patched_rtl, verification
