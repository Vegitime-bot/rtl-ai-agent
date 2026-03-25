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


def build_prompt(origin_rtl_dir: Path, uarch_origin: Path | None, uarch_new: Path | None,
                 algo_origin: Path, algo_new: Path, graph_ctx_text: str = "") -> str:
    prompt = []
    if graph_ctx_text:
        prompt.append(f"## Signal Causal Context (from Neo4j)\n{graph_ctx_text}\n")
    prompt += [
        "You are an RTL engineer. Generate a new Verilog module based on the deltas.",
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
            return build_prompt(origin_rtl_dir, uarch_origin, uarch_new, algo_origin, algo_new, graph_ctx_text=graph_ctx_text), False

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
    output_max_tokens: int = 8192,
) -> tuple[str, dict]:
    """
    RTL을 생성하고 검증을 실행한다.
    검증 실패 시 실패 이유를 피드백으로 포함해 최대 max_retries회 재시도한다.

    반환: (최종 RTL 문자열, 최종 verification dict)
    """
    # 지연 import — orchestrator/ 내에서만 사용
    from verify import run_checks  # type: ignore

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
                token_budget=token_budget,
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
                    token_budget=token_budget,
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

        result = call_llm(prompt, cfg, system_prompt=system, max_tokens=output_max_tokens)
        current_rtl = sanitize_verilog(result)
        current_rtl = ensure_endmodule(current_rtl, cfg, max_tokens=output_max_tokens)

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
