"""Tests for the markdown conversion helper."""

from tools.convert_to_markdown import collect_files


def test_collect_files_allows_hidden_parent_directory(tmp_path):
    source = tmp_path / ".mirror" / "docs"
    source.mkdir(parents=True)
    visible = source / "intro.md"
    visible.write_text("# Intro\n\nContent", encoding="utf-8")

    files = collect_files(source)

    assert files == [visible]


def test_collect_files_skips_outside_symlink(tmp_path):
    source = tmp_path / "docs"
    outside = tmp_path / "outside"
    source.mkdir()
    outside.mkdir()
    visible = source / "intro.md"
    visible.write_text("# Intro\n\nContent", encoding="utf-8")
    target = outside / "secret.md"
    target.write_text("# Secret\n\nShould not export", encoding="utf-8")
    (source / "secret-link.md").symlink_to(target)

    files = collect_files(source)

    assert files == [visible]
