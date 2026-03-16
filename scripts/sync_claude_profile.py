#!/usr/bin/env python3
"""Copy the bundled Claude Code instruction profile into a target workspace."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

PROFILE_FILES = [
    "AGENTS.md",
    "SOUL.md",
    "HEARTBEAT.md",
]

TEMPLATE_MAP = {
    "IDENTITY.template.md": "IDENTITY.md",
    "USER.template.md": "USER.md",
    "TOOLS.template.md": "TOOLS.md",
}

SKILLS_SUBDIR = "skills"


def copy_file(src: Path, dest: Path, force: bool) -> None:
    if dest.exists() and not force:
        print(f"[skip] {dest} already exists (use --force to overwrite)")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    print(f"[copy] {src.name} -> {dest}")


def sync_profile(target: Path, force: bool) -> None:
    root = Path(__file__).resolve().parent.parent
    profile_dir = root / "claude_profile"
    if not profile_dir.exists():
        raise SystemExit(f"Profile directory not found: {profile_dir}")

    # Plain instruction files
    for filename in PROFILE_FILES:
        copy_file(profile_dir / filename, target / filename, force)

    # Templates (rename on copy)
    for template_name, dest_name in TEMPLATE_MAP.items():
        copy_file(profile_dir / template_name, target / dest_name, force)

    # Skills README (informational)
    skills_src = profile_dir / SKILLS_SUBDIR / "README.md"
    if skills_src.exists():
        copy_file(skills_src, target / SKILLS_SUBDIR / "README.md", force)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync Claude Code agent profile files")
    parser.add_argument(
        "--dest",
        type=Path,
        default=Path("~/.openclaw/workspace").expanduser(),
        help="Target workspace directory (default: ~/.openclaw/workspace)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files in the destination",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sync_profile(args.dest, args.force)


if __name__ == "__main__":
    main()
