"""Tests for the markdown conversion helper."""

from tools.convert_to_markdown import collect_files


def test_collect_files_allows_hidden_parent_directory(tmp_path):
    wiki = tmp_path / ".mirror" / "docs"
    wiki.mkdir(parents=True)
    visible = wiki / "intro.md"
    visible.write_text("# Intro\n\nContent", encoding="utf-8")

    files = collect_files(wiki)

    assert files == [visible]
