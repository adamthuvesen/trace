"""Every inline pyright ignore names its rule and gives a reason. No file turns lint off file-wide."""

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIPPED_DIRS = {
    ".git",
    ".venv",
    ".verify",
    ".uv-cache",
    ".ruff_cache",
    ".pytest_cache",
    "target",
    "node_modules",
    "__pycache__",
}
PYRIGHT_IGNORE = re.compile(r"#\s*pyright:\s*ignore\b")
PYRIGHT_IGNORE_WITH_REASON = re.compile(r"#\s*pyright:\s*ignore\[[\w, ]+\]\s*(?:--|#)\s*\S{2,}")
FILE_WIDE_RUFF_NOQA = re.compile(r"^\s*#\s*(?:ruff|flake8):\s*noqa", re.IGNORECASE)


def is_python_file(path: Path) -> bool:
    if path.suffix:
        return path.suffix in {".py", ".pyi"}
    with path.open("rb") as handle:
        first_line = handle.readline()
    return first_line.startswith(b"#!") and b"python" in first_line


def python_files() -> list[Path]:
    found: list[Path] = []
    for directory, subdirectories, names in os.walk(ROOT):
        subdirectories[:] = sorted(d for d in subdirectories if d not in SKIPPED_DIRS)
        found += [path for name in sorted(names) if is_python_file(path := Path(directory, name))]
    return [path for path in found if path != Path(__file__).resolve()]


def offending_lines() -> list[str]:
    found: list[str] = []
    for path in python_files():
        for number, line in enumerate(path.read_text(errors="replace").splitlines(), start=1):
            if (
                PYRIGHT_IGNORE.search(line) and not PYRIGHT_IGNORE_WITH_REASON.search(line)
            ) or FILE_WIDE_RUFF_NOQA.match(line):
                found.append(f"{path.relative_to(ROOT)}:{number}")
    return found


def test_no_suppression_lacks_a_rule_or_a_reason() -> None:
    found = offending_lines()
    assert not found, (
        "Write `# pyright: ignore[rule] -- reason`, and name the rule in any `# ruff: noqa`: "
        + ", ".join(found[:10])
    )


def test_the_patterns_still_match_known_offences() -> None:
    assert PYRIGHT_IGNORE.search("x = 1  # pyright: ignore")
    assert PYRIGHT_IGNORE.search("x = 1  # pyright: ignore[reportFoo]")
    assert PYRIGHT_IGNORE_WITH_REASON.search("x = 1  # pyright: ignore[reportFoo] -- stub lacks it")
    assert not PYRIGHT_IGNORE_WITH_REASON.search("x = 1  # pyright: ignore[reportFoo]")
    assert FILE_WIDE_RUFF_NOQA.match("# ruff: noqa")
    assert FILE_WIDE_RUFF_NOQA.match("# ruff: noqa: F401")
