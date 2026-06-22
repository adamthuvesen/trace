#!/usr/bin/env python3
"""Fail if any trace_search module exceeds the line-count budget."""

from __future__ import annotations

from pathlib import Path

MAX_LINES = 1000
ROOT = Path(__file__).resolve().parents[1] / "src" / "trace_search"


def main() -> int:
    failures: list[str] = []
    for path in sorted(ROOT.rglob("*.py")):
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        if line_count > MAX_LINES:
            failures.append(f"{path.name}: {line_count} lines (max {MAX_LINES})")
    if failures:
        print("Module size check failed:")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("Module size check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
