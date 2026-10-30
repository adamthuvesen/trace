"""A file-level `# pyright:` mode comment must not turn strict type checking off for that file."""

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


def tracked_python_files() -> list[Path]:
    env = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
    listing = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, env=env, capture_output=True, check=True
    ).stdout.decode()
    paths = (ROOT / name for name in listing.split("\0") if name)
    return [path for path in paths if path.is_file() and is_python_file(path)]


def test_no_file_downgrades_type_checking_mode() -> None:
    downgrades = [
        f"{path.relative_to(ROOT)}:{number}"
        for path in tracked_python_files()
        for number, line in enumerate(path.read_text(errors="replace").splitlines(), start=1)
        if DOWNGRADE.match(line)
    ]
    assert not downgrades, "file-level `# pyright:` comment turns strict mode off: " + ", ".join(
        downgrades
    )
