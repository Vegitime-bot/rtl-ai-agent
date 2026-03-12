from __future__ import annotations

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
        "- Reflect masking stage and MixColumns skipping per new spec.",
        "- Return valid Verilog code only.",
    ]
    return "\n".join(prompt)


def generate_rtl(cfg: dict, origin_v: Path, uarch_origin: Path, uarch_new: Path, algo_origin: Path, algo_new: Path, output: Path) -> str:
    prompt = build_prompt(origin_v, uarch_origin, uarch_new, algo_origin, algo_new)
    result = call_llm(prompt, cfg, system_prompt="You generate production-quality synthesizable Verilog.")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(result)
    return result
