"""Tests for shared KB file iteration."""

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
