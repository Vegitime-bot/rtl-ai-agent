from __future__ import annotations

import warnings
from pathlib import Path

from llm_utils import call_llm


def build_prompt(origin_v: Path, uarch_origin: Path, uarch_new: Path, algo_origin: Path, algo_new: Path) -> str:
    prompt = [
        "You are an RTL engineer. Generate a new Verilog module based on the deltas.",
        "=== Original RTL ===",
        origin_v.read_text(),
        "=== Micro-architecture (origin) ===",
        uarch_origin.read_text(),
        "=== Micro-architecture (new) ===",
        uarch_new.read_text(),
        "=== Algorithm (origin) ===",
        algo_origin.read_text(),
        "=== Algorithm (new) ===",
        algo_new.read_text(),
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


def ensure_endmodule(content: str, cfg: dict) -> str:
    attempt = 0
    full = content
    while "endmodule" not in full and attempt < 2:
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
        )
        full = f"{full}\n{sanitize_verilog(extra)}"
        attempt += 1
    return full


def generate_rtl(cfg: dict, origin_v: Path, uarch_origin: Path, uarch_new: Path, algo_origin: Path, algo_new: Path, output: Path) -> str:
    prompt = build_prompt(origin_v, uarch_origin, uarch_new, algo_origin, algo_new)
    result = call_llm(prompt, cfg, system_prompt="You generate production-quality synthesizable Verilog.")
    clean = sanitize_verilog(result)
    clean = ensure_endmodule(clean, cfg)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(clean)
    return clean


def _build_retry_prompt(
    prev_rtl: str,
    verification: dict,
    origin_v: Path,
    uarch_origin: Path,
    uarch_new: Path,
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
        origin_v.read_text(),
        "=== Micro-architecture (origin) ===",
        uarch_origin.read_text(),
        "=== Micro-architecture (new) ===",
        uarch_new.read_text(),
        "=== Algorithm (origin) ===",
        algo_origin.read_text(),
        "=== Algorithm (new) ===",
        algo_new.read_text(),
        "",
        "=== Requirements ===",
        "- Fix ALL verification failures listed above.",
        "- Keep the same module ports unless specification says otherwise.",
        "- Implement every behavioral delta described in the spec.",
        "- Output synthesizable Verilog only (no Markdown fences, no commentary).",
        "- Ensure the module terminates with 'endmodule'.",
    ]
    return "\n".join(prompt)


def generate_rtl_with_retry(
    cfg: dict,
    origin_v: Path,
    uarch_origin: Path,
    uarch_new: Path,
    algo_origin: Path,
    algo_new: Path,
    output: Path,
    causal_graph_path: Path | None = None,
    max_retries: int = 2,
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
            prompt = build_prompt(origin_v, uarch_origin, uarch_new, algo_origin, algo_new)
            system = "You generate production-quality synthesizable Verilog."
        else:
            prompt = _build_retry_prompt(
                current_rtl, verification,
                origin_v, uarch_origin, uarch_new, algo_origin, algo_new,
                attempt,
            )
            system = (
                "You are an RTL engineer fixing a Verilog module that failed automated verification. "
                "Address every listed failure. Return corrected Verilog code only."
            )

        result = call_llm(prompt, cfg, system_prompt=system)
        current_rtl = sanitize_verilog(result)
        current_rtl = ensure_endmodule(current_rtl, cfg)

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
