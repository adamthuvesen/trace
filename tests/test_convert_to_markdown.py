"""Tests for the markdown conversion helper."""

from tools.convert_to_markdown import collect_files


def test_collect_files_allows_hidden_parent_directory(tmp_path):
    wiki = tmp_path / ".mirror" / "docs"
    wiki.mkdir(parents=True)
    visible = wiki / "intro.md"
    visible.write_text("# Intro\n\nContent", encoding="utf-8")

    files = collect_files(wiki)

    assert files == [visible]


def test_collect_files_skips_outside_symlink(tmp_path):
    wiki = tmp_path / "docs"
    outside = tmp_path / "outside"
    wiki.mkdir()
    outside.mkdir()
    visible = wiki / "intro.md"
    visible.write_text("# Intro\n\nContent", encoding="utf-8")
    target = outside / "secret.md"
    target.write_text("# Secret\n\nShould not export", encoding="utf-8")
    (wiki / "secret-link.md").symlink_to(target)

    files = collect_files(wiki)

    assert files == [visible]
