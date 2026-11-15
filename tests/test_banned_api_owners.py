"""A per-file TID251 ignore lifts every ban for that file, so only src/ and tools/ owners listed in pyproject.toml have one."""

import ast
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def ruff_lint_config() -> dict[str, Any]:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return config["tool"]["ruff"]["lint"]


def owner_files() -> set[str]:
    """Files outside tests/ that may use banned modules, read from the per-file ignores."""
    ignores = ruff_lint_config()["per-file-ignores"]
    return {path for path in ignores if not path.startswith("tests/")}


def banned_names() -> set[str]:
    return set(ruff_lint_config()["flake8-tidy-imports"]["banned-api"])


# The bar's named process, network and paid-SDK modules. Deleting one from the ban list must fail.
BAR_NAMED_BANS = {
    "subprocess",
    "pty",
    "os.system",
    "os.popen",
    "asyncio.subprocess",
    "socket",
    "http.client",
    "urllib.request",
    "requests",
    "httpx",
    "openai",
    "anthropic",
    "snowflake",
}


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
    assert ignoring == {"tests/**", *owner_files()}, (
        "Only tests/** and the owner files may ignore TID251. Remove the ignore, or list the "
        f"file as an owner in [tool.ruff.lint.per-file-ignores]. Found: {sorted(ignoring)}"
    )
    for path in owner_files():
        assert (ROOT / path).is_file(), (
            f"owner file {path} does not exist. Remove its entry from "
            "[tool.ruff.lint.per-file-ignores] in pyproject.toml, or fix the path."
        )


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
    assert done.returncode == 0, (
        "A noqa comment hides a banned import. Remove the noqa and move the call into an owner "
        "file in [tool.ruff.lint.per-file-ignores]:\n" + done.stdout
    )


def test_ban_report_finds_a_noqa_silenced_import(tmp_path: Path) -> None:
    planted = tmp_path / "planted.py"
    planted.write_text("import requests  # noqa: TID251\n", encoding="utf-8")
    done = ruff_ban_report(str(planted))
    assert done.returncode != 0 and "requests" in done.stdout


def nested_ruff_configs(root: Path) -> list[str]:
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    return [
        path
        for path in listed
        if Path(path).name in {"ruff.toml", ".ruff.toml"}
        or (path != "pyproject.toml" and Path(path).name == "pyproject.toml")
    ]


def test_no_nested_ruff_config_overrides_the_ban() -> None:
    nested = nested_ruff_configs(ROOT)
    assert not nested, (
        "A nested ruff config replaces the root bans. Delete it and put the setting in the root "
        f"pyproject.toml: {nested}"
    )


def test_nested_ruff_config_scan_finds_a_planted_config(tmp_path: Path) -> None:
    subprocess.run(
        ["git", "init", "-q", str(tmp_path)],
        env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
        check=True,
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "ruff.toml").write_text("[lint]\nselect = []\n", encoding="utf-8")
    assert nested_ruff_configs(tmp_path) == ["src/ruff.toml"]


def test_ban_list_keeps_every_module_the_bar_names() -> None:
    missing = sorted(BAR_NAMED_BANS - banned_names())
    assert not missing, (
        "These modules must stay in [tool.ruff.lint.flake8-tidy-imports.banned-api] in "
        f"pyproject.toml. Restore them: {missing}"
    )


def test_detector_finds_an_extra_banned_module() -> None:
    source = "import subprocess\nimport requests\nimport os\nos.system('x')\n"
    assert banned_uses(source, banned_names()) == {"subprocess", "requests", "os.system"}


# A TID251 ban is global and src needs these calls, so the tests-only ban is checked here.
TEST_TIME_CALLS = {
    "time.sleep",
    "asyncio.sleep",
    "time.time",
    "time.perf_counter",
    "time.monotonic",
}

# The one bounded poll for real processes and servers. It is the only test file that may sleep.
POLLING_HELPER = ROOT / "tests" / "polling.py"


def time_calls_in(paths: list[Path], root: Path = ROOT) -> list[str]:
    found: list[str] = []
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                name = f"{node.value.id}.{node.attr}"
            elif isinstance(node, ast.ImportFrom) and node.module in {"time", "asyncio"}:
                name = next(
                    (
                        f"{node.module}.{alias.name}"
                        for alias in node.names
                        if f"{node.module}.{alias.name}" in TEST_TIME_CALLS
                    ),
                    "",
                )
            else:
                continue
            if name in TEST_TIME_CALLS:
                found.append(f"{path.relative_to(root)}:{node.lineno}")
    return found


def test_time_call_detector_finds_sleeps_and_clocks(tmp_path: Path) -> None:
    probe = tmp_path / "test_probe.py"
    probe.write_text(
        "import asyncio\nimport time\nfrom time import monotonic\n"
        "time.sleep(0)\nasyncio.sleep(0)\ntime.time()\ntime.strftime('%Y')\n",
        encoding="utf-8",
    )
    assert time_calls_in([probe], tmp_path) == [f"test_probe.py:{n}" for n in (3, 4, 5, 6)]


def test_tests_do_not_sleep_or_read_the_wall_clock() -> None:
    found = time_calls_in(
        sorted(path for path in (ROOT / "tests").rglob("*.py") if path != POLLING_HELPER)
    )
    assert not found, (
        "Tests must not sleep or read the wall clock. Wait on an event, or inject a fake clock "
        "or sleep argument. Found: " + ", ".join(found)
    )
