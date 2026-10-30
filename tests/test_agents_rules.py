"""The AGENTS.md Enforced Rules table must cite files, tests, and keys that exist."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _definition(path: Path, name: str) -> re.Pattern[str]:
    if path.suffix == ".py":
        return re.compile(
            rf"^\s*(?:(?:async\s+)?def {name}\(|class {name}\b|{name} =)", re.M
        )
    if path.name == "justfile":
        return re.compile(rf"^{re.escape(name)}\b[^\n]*:", re.M)
    if path.suffix == ".toml":
        key = re.escape(name)
        return re.compile(rf"^(?:\[\[?{key}[\].]|{key}\s*=)", re.M)
    raise AssertionError(f"Cite a .py, .toml, or justfile name, not {path.name}")


def test_enforced_rules_cite_real_files():
    agents = (REPO_ROOT / "AGENTS.md").read_text()
    assert "\n## Enforced Rules\n" in agents, (
        "AGENTS.md must keep its ## Enforced Rules section."
    )
    section = agents.split("\n## Enforced Rules\n", 1)[1].split("\n## ", 1)[0]
    rows = [line for line in section.splitlines() if line.startswith("| ")][2:]
    assert rows, "AGENTS.md needs an ## Enforced Rules table with at least one row."
    missing = []
    for row in rows:
        cited = re.findall(r"`([^`]+)`", row.split("|")[2])
        if not cited:
            missing.append(f"{row.split('|')[1].strip()}: no citation")
        for citation in cited:
            relative, _, name = citation.partition("::")
            path = REPO_ROOT / relative
            if not path.exists() or (
                name and not _definition(path, name).search(path.read_text())
            ):
                missing.append(citation)
    assert not missing, (
        "AGENTS.md Enforced Rules cites paths or names that do not exist. "
        f"Fix the 'Enforced by' column or restore the check: {missing}"
    )


def test_python_citations_match_async_and_sync_definitions():
    source = "async def control(ctx):\n    pass\n\ndef drive(ctx):\n    pass\n"
    for name in ("control", "drive"):
        assert _definition(Path("drives.py"), name).search(source), name
    assert not _definition(Path("drives.py"), "missing").search(source)
