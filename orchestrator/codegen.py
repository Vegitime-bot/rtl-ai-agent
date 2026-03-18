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
