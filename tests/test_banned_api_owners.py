"""A per-file TID251 ignore lifts every ban for that file, so each owner is held to its own modules."""

import ast
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

OWNERS: dict[str, set[str]] = {
    "tools/verify_package.py": {"subprocess"},
    "tools/eval/provenance.py": {"subprocess"},
    "tests/test_runtime_boundaries.py": {"subprocess"},
    "tests/test_runtime_hardening.py": {"subprocess"},
    "tests/test_strict_mode.py": {"subprocess"},
    "tests/test_transports.py": {"subprocess", "socket", "http.client"},
    ".agents/skills/verify-trace/drives.py": {"subprocess", "socket"},
    ".agents/skills/verify-trace/verify": {"subprocess", "os.execvp"},
}


def ruff_lint_config() -> dict[str, Any]:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return config["tool"]["ruff"]["lint"]


def banned_names() -> set[str]:
    return set(ruff_lint_config()["flake8-tidy-imports"]["banned-api"])


def used_names(source: str) -> set[str]:
    """Dotted names a file imports or references."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Attribute):
            parts = [node.attr]
            value = node.value
            while isinstance(value, ast.Attribute):
                parts.append(value.attr)
                value = value.value
            if isinstance(value, ast.Name):
                names.add(".".join([value.id, *reversed(parts)]))
    return names


def banned_uses(source: str, banned: set[str]) -> set[str]:
    return {
        ban
        for name in used_names(source)
        for ban in banned
        if name == ban or name.startswith(f"{ban}.")
    }


def test_only_named_owners_ignore_tid251() -> None:
    lint = ruff_lint_config()
    assert "TID251" not in lint.get("ignore", [])
    ignoring = {path for path, rules in lint["per-file-ignores"].items() if "TID251" in rules}
    assert ignoring == set(OWNERS)


def test_each_owner_uses_only_its_own_banned_modules() -> None:
    banned = banned_names()
    for path, allowed in OWNERS.items():
        extra = banned_uses((ROOT / path).read_text(encoding="utf-8"), banned) - allowed
        assert not extra, f"{path} uses banned modules outside its ownership: {sorted(extra)}"


def test_detector_finds_an_extra_banned_module() -> None:
    source = "import subprocess\nimport requests\nimport os\nos.system('x')\n"
    assert banned_uses(source, banned_names()) == {"subprocess", "requests", "os.system"}
