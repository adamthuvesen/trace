"""A file-level `# pyright:` mode comment must not turn strict type checking off for that file."""

import ast
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOWNGRADE = re.compile(
    r"^\s*#\s*pyright:\s*(?:[^#\n]*,\s*)?(?:basic|standard|off|recommended|all|strict\s*=\s*false)\b"
)


def is_python_file(path: Path) -> bool:
    if path.suffix:
        return path.suffix == ".py"
    with path.open("rb") as handle:
        first_line = handle.readline()
    return first_line.startswith(b"#!") and b"python" in first_line


def listed_python_files(root: Path) -> list[Path]:
    """Tracked files plus untracked ones git does not ignore, so an unstaged file is scanned too."""
    env = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
    listing = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        env=env,
        capture_output=True,
        check=True,
    ).stdout.decode()
    paths = (root / name for name in listing.split("\0") if name)
    return [path for path in paths if path.is_file() and is_python_file(path)]


def downgrades(root: Path) -> list[str]:
    return [
        f"{path.relative_to(root)}:{number}"
        for path in listed_python_files(root)
        for number, line in enumerate(path.read_text(errors="replace").splitlines(), start=1)
        if DOWNGRADE.match(line)
    ]


def test_detector_finds_an_unstaged_downgrade(tmp_path: Path) -> None:
    env = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, env=env, check=True)
    (tmp_path / "clean.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "loose.py").write_text("# pyright: basic\n", encoding="utf-8")
    assert downgrades(tmp_path) == ["loose.py:1"]


def test_no_file_downgrades_type_checking_mode() -> None:
    found = downgrades(ROOT)
    assert not found, (
        "A file-level `# pyright:` comment turns strict mode off. Remove it; to skip one line, "
        "write `# pyright: ignore[rule] -- reason`. Found: " + ", ".join(found)
    )


SKIP_CALLS = {"pytest.mark.skip", "pytest.mark.xfail", "pytest.skip", "unittest.skip"}
SKIP_DECORATORS = {"pytest.mark.skip", "pytest.mark.xfail", "unittest.skip"}


def dotted_name(node: ast.expr) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def reasonless_skip_lines(source: str) -> list[int]:
    found: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and dotted_name(node.func) in SKIP_CALLS:
            reason = next((kw.value for kw in node.keywords if kw.arg == "reason"), None)
            if reason is None and dotted_name(node.func) != "pytest.mark.xfail" and node.args:
                reason = node.args[0]
            if reason is None or (
                isinstance(reason, ast.Constant) and not str(reason.value).strip()
            ):
                found.append(node.lineno)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            found += [
                decorator.lineno
                for decorator in node.decorator_list
                if dotted_name(decorator) in SKIP_DECORATORS
            ]
    return sorted(found)


def test_detector_finds_a_reasonless_skip() -> None:
    assert reasonless_skip_lines("@pytest.mark.skip\ndef test_x():\n    pass\n") == [1]
    assert reasonless_skip_lines("pytest.skip('  ')\n") == [1]
    assert reasonless_skip_lines("pytest.mark.xfail(strict=True)\n") == [1]
    assert reasonless_skip_lines("pytest.mark.skip(reason='waits on a live API')\n") == []


def test_every_skip_gives_a_reason() -> None:
    found = [
        f"{path.relative_to(ROOT)}:{line}"
        for path in listed_python_files(ROOT)
        for line in reasonless_skip_lines(path.read_text(errors="replace"))
    ]
    assert not found, (
        'Every skip, xfail, and unittest skip needs a non-empty reason. Add reason="<why>", or '
        "pass the reason as the first argument. Found: " + ", ".join(found)
    )
