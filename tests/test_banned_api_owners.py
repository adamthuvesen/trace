"""A per-file TID251 ignore lifts every ban for that file, so each owner is held to its own modules."""

import ast
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

OWNERS: dict[str, set[str]] = {
    "tests/test_banned_api_owners.py": {"subprocess"},
    "tools/verify_package.py": {"subprocess"},
    "tools/eval/provenance.py": {"subprocess"},
    "tests/test_runtime_boundaries.py": {"subprocess"},
    "tests/test_runtime_hardening.py": {"subprocess"},
    "tests/test_strict_mode.py": {"subprocess"},
    "tests/test_verify_guards.py": {"subprocess"},
    "tests/test_transports.py": {"subprocess", "socket", "http.client"},
    ".agents/skills/verify-trace/drives.py": {"subprocess", "socket", "asyncio.open_connection"},
    ".agents/skills/verify-trace/verify": {"subprocess", "os.execvp"},
}


def ruff_lint_config() -> dict[str, Any]:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return config["tool"]["ruff"]["lint"]


def banned_names() -> set[str]:
    return set(ruff_lint_config()["flake8-tidy-imports"]["banned-api"])


def used_names(source: str) -> set[str]:
    """Dotted names a file reaches through its imports, with `as` aliases resolved."""
    tree = ast.parse(source)
    bound: dict[str, str] = {}
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
                bound[alias.asname or alias.name.split(".")[0]] = (
                    alias.name if alias.asname else alias.name.split(".")[0]
                )
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            for alias in node.names:
                names.add(f"{node.module}.{alias.name}")
                bound[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            parts = [node.attr]
            value = node.value
            while isinstance(value, ast.Attribute):
                parts.append(value.attr)
                value = value.value
            if isinstance(value, ast.Name) and value.id in bound:
                names.add(".".join([bound[value.id], *reversed(parts)]))
    return names


def banned_uses(source: str, banned: set[str]) -> set[str]:
    return {
        ban
        for name in used_names(source)
        for ban in banned
        if name == ban or name.startswith(f"{ban}.")
    }


SILENCES_TID251 = {"ALL", "TID", "TID2", "TID25", "TID251"}


def test_only_named_owners_ignore_tid251() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    ruff = config["tool"]["ruff"]
    lint = ruff_lint_config()
    assert not (ROOT / "ruff.toml").exists()
    assert not (ROOT / ".ruff.toml").exists()
    assert not ruff.get("exclude") and not ruff.get("extend-exclude") and not lint.get("exclude")
    assert not lint.get("extend-per-file-ignores")
    assert "TID251" in lint["select"]
    assert not SILENCES_TID251 & set(lint.get("ignore", []))
    ignoring = {
        path for path, rules in lint["per-file-ignores"].items() if SILENCES_TID251 & set(rules)
    }
    assert ignoring == set(OWNERS)


def ruff_ban_report(target: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--config",
            str(ROOT / "pyproject.toml"),
            "--ignore-noqa",
            "--select",
            "TID251",
            "--quiet",
            "--output-format",
            "concise",
            target,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_no_inline_comment_silences_the_ban() -> None:
    """With `noqa` ignored, only the owners' per-file ignores may leave a banned use unreported."""
    done = ruff_ban_report(".")
    assert done.returncode == 0, "a noqa comment hides a banned import:\n" + done.stdout


def test_ban_report_finds_a_noqa_silenced_import(tmp_path: Path) -> None:
    planted = tmp_path / "planted.py"
    planted.write_text("import requests  # noqa: TID251\n", encoding="utf-8")
    done = ruff_ban_report(str(planted))
    assert done.returncode != 0 and "requests" in done.stdout


def test_no_nested_ruff_config_overrides_the_ban() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    nested = [
        path
        for path in tracked
        if Path(path).name in {"ruff.toml", ".ruff.toml"}
        or (path != "pyproject.toml" and Path(path).name == "pyproject.toml")
    ]
    assert not nested, f"a nested ruff config can silence the ban: {nested}"


def test_each_owner_uses_only_its_own_banned_modules() -> None:
    banned = banned_names()
    for path, allowed in OWNERS.items():
        extra = banned_uses((ROOT / path).read_text(encoding="utf-8"), banned) - allowed
        assert not extra, f"{path} uses banned modules outside its ownership: {sorted(extra)}"


def test_detector_finds_an_extra_banned_module() -> None:
    source = "import subprocess\nimport requests\nimport os\nos.system('x')\n"
    assert banned_uses(source, banned_names()) == {"subprocess", "requests", "os.system"}
