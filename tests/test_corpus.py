"""Tests for shared KB file iteration."""

import os
from pathlib import Path

from trace_search.extraction.corpus import iter_kb_files


def test_iter_kb_files_matches_fixture_layout(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "architecture").mkdir()
    (kb / "rfcs").mkdir()
    (kb / "architecture" / "intro.md").write_text("# Intro\n", encoding="utf-8")
    (kb / "architecture" / "notes.md").write_text("# Notes\n", encoding="utf-8")
    (kb / "rfcs" / "001.md").write_text("# RFC\n", encoding="utf-8")
    (kb / "rfcs" / "002.py").write_text("x = 1\n", encoding="utf-8")
    (kb / ".hidden").mkdir()
    (kb / ".hidden" / "secret.md").write_text("hidden\n", encoding="utf-8")

    paths = sorted(p.relative_to(kb).as_posix() for p in iter_kb_files(kb))
    assert paths == [
        "architecture/intro.md",
        "architecture/notes.md",
        "rfcs/001.md",
        "rfcs/002.py",
    ]


def test_iter_kb_files_respects_root_subfolder(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    (kb / "a").mkdir(parents=True)
    (kb / "b").mkdir(parents=True)
    (kb / "a" / "one.md").write_text("a\n", encoding="utf-8")
    (kb / "b" / "two.md").write_text("b\n", encoding="utf-8")

    paths = [p.name for p in iter_kb_files(kb, root=kb / "a")]
    assert paths == ["one.md"]


def _write_files(kb: Path, rel_paths: list[str]) -> None:
    for rel in rel_paths:
        path = kb / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {rel}\n", encoding="utf-8")


def test_traceignore_allowlist_with_negation_keeps_kb_relative_paths(
    tmp_path: Path,
) -> None:
    kb = tmp_path / "kb"
    _write_files(
        kb,
        [
            "README.md",
            "raw/drop.md",
            "wiki/index.md",
            "wiki/concepts/foo.md",
            "wiki/log.md",
            "wiki/log/2026-09.md",
            "wiki/concepts/log.md",
        ],
    )
    (kb / ".traceignore").write_text(
        "/*\n!/wiki/\n/wiki/log.md\n/wiki/log/\n", encoding="utf-8"
    )

    paths = sorted(p.relative_to(kb).as_posix() for p in iter_kb_files(kb))
    assert paths == [
        "wiki/concepts/foo.md",
        "wiki/concepts/log.md",
        "wiki/index.md",
    ]


def test_traceignore_directory_pattern_matches_nested_files(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    _write_files(kb, ["docs/a.md", "docs/drafts/b.md", "notes/drafts/deep/c.md"])
    (kb / ".traceignore").write_text("drafts/\n", encoding="utf-8")

    paths = sorted(p.relative_to(kb).as_posix() for p in iter_kb_files(kb))
    assert paths == ["docs/a.md"]


def test_traceignore_edits_take_effect_without_restart(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    _write_files(kb, ["a.md", "b.md"])
    ignore_file = kb / ".traceignore"
    ignore_file.write_text("a.md\n", encoding="utf-8")
    assert [p.name for p in iter_kb_files(kb)] == ["b.md"]

    ignore_file.write_text("b.md\n", encoding="utf-8")
    stat = ignore_file.stat()
    os.utime(ignore_file, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    assert [p.name for p in iter_kb_files(kb)] == ["a.md"]

    ignore_file.unlink()
    assert sorted(p.name for p in iter_kb_files(kb)) == ["a.md", "b.md"]
