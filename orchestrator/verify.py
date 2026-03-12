from __future__ import annotations

import re
from pathlib import Path

MODULE_RE = re.compile(r"module\s+\w+")


def run_basic_checks(path: Path) -> dict:
    if not path.exists():
        return {"status": "fail", "detail": "output file missing"}
    text = path.read_text()
    if "TODO" in text:
        return {"status": "fail", "detail": "contains TODO"}
    if not MODULE_RE.search(text):
        return {"status": "fail", "detail": "no module declaration"}
    return {"status": "pass", "detail": "syntax placeholder checks passed"}
