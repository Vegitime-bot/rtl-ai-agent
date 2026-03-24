#!/usr/bin/env python3
"""Utility to run Surelog and export UHDM JSON artifacts."""
from __future__ import annotations

import argparse
import datetime as dt
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_SCHEMA_CANDIDATES = [
    Path("/opt/homebrew/share/uhdm/UHDM.capnp"),
    Path("/usr/local/share/uhdm/UHDM.capnp"),
    Path("/usr/share/uhdm/UHDM.capnp"),
]


def find_first_existing(paths: list[Path]) -> Path | None:
    for candidate in paths:
        if candidate.exists():
            return candidate
    return None


def append_log(log_file: Path, message: str) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(f"{timestamp}  {message}\n")


def run_command(cmd: list[str], cwd: Path | None = None, log_file: Path | None = None) -> None:
    if log_file is not None:
        append_log(log_file, " ".join(cmd))
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def convert_uhdm_to_json(schema: Path, binary_path: Path, json_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with binary_path.open("rb") as stdin, json_path.open("wb") as stdout:
        subprocess.run(
            [
                "capnp",
                "convert",
                "packed:json",
                str(schema),
                "UhdmRoot",
            ],
            check=True,
            stdin=stdin,
            stdout=stdout,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Surelog and emit UHDM artifacts")
    parser.add_argument("rtl", type=Path, nargs="?", default=Path("inputs/rtl"),
                        help="RTL .v/.sv 파일 또는 디렉토리 (기본: inputs/rtl/)")
    parser.add_argument("--surelog", default="surelog", help="Surelog executable (default: surelog on PATH)")
    parser.add_argument("--schema", type=Path, help="Path to UHDM.capnp schema (auto-detected if omitted)")
    parser.add_argument("--build-dir", type=Path, default=Path("build"), help="Output directory for artifacts")
    parser.add_argument("--binary-out", type=Path, default=None, help="Optional explicit path for UHDM binary copy")
    parser.add_argument("--json-out", type=Path, default=None, help="Optional explicit path for UHDM JSON output")
    parser.add_argument("--log-file", type=Path, default=Path("logs/commands.log"), help="Command log file (default: logs/commands.log)")
    parser.add_argument("--no-clean", action="store_true", help="Do not delete existing slpp_all directory before running")
    parser.add_argument("--extra", nargs=argparse.REMAINDER, help="Additional flags passed to Surelog after the RTL paths")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project_root = Path.cwd()
    rtl_input = (project_root / args.rtl).resolve()

    # 디렉토리면 하위 *.v / *.sv 전체 수집, 단일 파일이면 그대로
    if rtl_input.is_dir():
        rtl_files = sorted(rtl_input.glob("*.v")) + sorted(rtl_input.glob("*.sv"))
        if not rtl_files:
            raise SystemExit(f"RTL 파일이 없습니다: {rtl_input}")
        print(f"[run_surelog] {len(rtl_files)} RTL file(s) from {rtl_input}")
    elif rtl_input.is_file():
        rtl_files = [rtl_input]
    else:
        raise SystemExit(f"RTL 경로를 찾을 수 없습니다: {rtl_input}")

    schema_path = args.schema
    if schema_path is None:
        schema_path = find_first_existing(DEFAULT_SCHEMA_CANDIDATES)
    if schema_path is None:
        raise SystemExit("Could not locate UHDM.capnp schema. Use --schema to specify it explicitly.")

    build_dir = (project_root / args.build_dir).resolve()
    build_dir.mkdir(parents=True, exist_ok=True)
    binary_out = (project_root / args.binary_out).resolve() if args.binary_out else (build_dir / "origin.uhdm.bin")
    json_out = (project_root / args.json_out).resolve() if args.json_out else (build_dir / "origin.uhdm.json")
    log_file = (project_root / args.log_file).resolve()

    slpp_dir = project_root / "slpp_all"
    if slpp_dir.exists() and not args.no_clean:
        shutil.rmtree(slpp_dir)

    surelog_cmd = [
        args.surelog,
        "-parse",
        "-sverilog",
    ] + [str(f) for f in rtl_files]   # 다중 파일 전달
    if args.extra:
        surelog_cmd.extend(args.extra)

    run_command(surelog_cmd, cwd=project_root, log_file=log_file)

    uhdm_bin = slpp_dir / "surelog.uhdm"
    if not uhdm_bin.exists():
        raise SystemExit(f"Surelog did not produce UHDM DB at {uhdm_bin}")

    binary_out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(uhdm_bin, binary_out)

    convert_uhdm_to_json(schema_path, binary_out, json_out)
    print(f"[run_surelog] UHDM binary: {binary_out}")
    print(f"[run_surelog] UHDM JSON: {json_out}")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"Command failed with exit code {exc.returncode}: {exc.cmd}")
