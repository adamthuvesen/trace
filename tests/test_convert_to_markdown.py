"""Tests for the markdown conversion helper."""

import os
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from tools.convert_to_markdown import (
    CONVERTERS,
    build_conversion_plan,
    collect_files,
    main,
    process_files,
    provenance_path,
)


def test_collect_files_allows_hidden_parent_directory(tmp_path: Path) -> None:
    source = tmp_path / ".mirror" / "docs"
    source.mkdir(parents=True)
    visible = source / "intro.md"
    visible.write_text("# Intro\n\nContent", encoding="utf-8")

    files = collect_files(source)

    assert files == [visible]


def test_collect_files_skips_outside_symlink(tmp_path: Path) -> None:
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


def run_conversion(source: Path, output: Path, *arguments: str) -> Result:
    return CliRunner().invoke(
        main,
        ["--source-path", str(source), "--output-dir", str(output), *arguments],
    )


def test_collision_rejects_entire_batch_before_writes(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "first.md").write_text("first")
    (source / "report.md").write_text("markdown")
    (source / "report.txt").write_text("text")
    output = tmp_path / "output"

    result = run_conversion(source, output)

    assert result.exit_code != 0
    assert "Destination collision" in result.stderr
    assert not output.exists()


def test_verified_source_change_regenerates_output(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    document = source / "intro.txt"
    document.write_text("first")
    output = tmp_path / "output"

    first = process_files([document], source, output, False, False)
    unchanged = process_files([document], source, output, False, False)
    document.write_text("other")
    changed = process_files([document], source, output, False, False)

    assert first.converted == 1
    assert unchanged.unchanged == 1
    assert changed.converted == 1
    assert (output / "intro.md").read_text() == "other"
    assert provenance_path(output / "intro.md").is_file()


def test_existing_output_requires_explicit_force(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "intro.md").write_text("new")
    output = tmp_path / "output"
    output.mkdir()
    destination = output / "intro.md"
    destination.write_text("old")

    result = run_conversion(source, output)

    assert result.exit_code != 0
    assert "Unverified: 1" in result.stdout
    assert "--force" in result.stderr
    assert destination.read_text() == "old"
    assert not provenance_path(destination).exists()

    forced = run_conversion(source, output, "--force")

    assert forced.exit_code == 0
    assert destination.read_text() == "new"
    assert provenance_path(destination).exists()
    assert run_conversion(source, output).exit_code == 0


def test_edited_output_is_unverified(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    document = source / "intro.md"
    document.write_text("source")
    output = tmp_path / "output"
    process_files([document], source, output, False, False)
    (output / "intro.md").write_text("manual edit")

    stats = process_files([document], source, output, False, False)

    assert stats.unverified == 1
    assert stats.unchanged == 0
    assert (output / "intro.md").read_text() == "manual edit"


@pytest.mark.parametrize("row", ["3,4,5", "3"])
def test_malformed_csv_fails_without_replacing_good_output(tmp_path: Path, row: str) -> None:
    source = tmp_path / "source"
    source.mkdir()
    document = source / "rows.csv"
    document.write_text("left,right\n1,2\n")
    output = tmp_path / "output"
    assert run_conversion(source, output).exit_code == 0
    destination = output / "rows.md"
    previous_output = destination.read_bytes()
    previous_provenance = provenance_path(destination).read_bytes()
    document.write_text(f"left,right\n1,2\n{row}\n")

    result = run_conversion(source, output)

    assert result.exit_code != 0
    assert "Malformed CSV at line 3" in result.stderr
    assert destination.read_bytes() == previous_output
    assert provenance_path(destination).read_bytes() == previous_provenance


def test_failed_converter_preserves_last_good_output_and_processes_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    document = source / "intro.txt"
    document.write_text("original")
    output = tmp_path / "output"
    assert run_conversion(source, output).exit_code == 0
    destination = output / "intro.md"
    previous_provenance = provenance_path(destination).read_bytes()
    document.write_text("changed")
    (source / "other.md").write_text("independent")

    def failed_conversion(input_path: Path, output_path: Path) -> None:
        output_path.write_text("partial output")
        raise RuntimeError("document conversion failed")

    monkeypatch.setitem(CONVERTERS, ".txt", failed_conversion)

    result = run_conversion(source, output)

    assert result.exit_code != 0
    assert "document conversion failed" in result.stderr
    assert destination.read_text() == "original"
    assert provenance_path(destination).read_bytes() == previous_provenance
    assert (output / "other.md").read_text() == "independent"
    assert not list(output.glob(".trace-convert-*"))


def test_provenance_publish_failure_rolls_back_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    document = source / "intro.txt"
    document.write_text("original")
    output = tmp_path / "output"
    process_files([document], source, output, False, False)
    destination = output / "intro.md"
    previous_provenance = provenance_path(destination).read_bytes()
    document.write_text("changed")
    replace = os.replace

    def fail_provenance(source_path: Path, destination_path: Path) -> None:
        if destination_path == provenance_path(destination):
            raise OSError("cannot publish provenance")
        replace(source_path, destination_path)

    monkeypatch.setattr(os, "replace", fail_provenance)

    stats = process_files([document], source, output, False, False)

    assert stats.failed == 1
    assert destination.read_text() == "original"
    assert provenance_path(destination).read_bytes() == previous_provenance


@pytest.mark.parametrize("directory_link", [False, True])
def test_destination_symlink_rejects_batch_before_writes(
    tmp_path: Path, directory_link: bool
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    output = tmp_path / "output"
    output.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "intro.md"
    target.write_text("protected")
    (source / "first.md").write_text("first")
    if directory_link:
        (source / "linked").mkdir()
        (source / "linked" / "intro.md").write_text("new")
        (output / "linked").symlink_to(outside, target_is_directory=True)
    else:
        (source / "intro.md").write_text("new")
        (output / "intro.md").symlink_to(target)

    result = run_conversion(source, output, "--force")

    assert result.exit_code != 0
    assert "symlink" in result.stderr
    assert target.read_text() == "protected"
    assert not (output / "first.md").exists()


def test_plan_rejects_explicit_outside_source_symlink(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("protected")
    link = source / "linked.md"
    link.symlink_to(outside)

    with pytest.raises(ValueError, match="Source symlink escapes"):
        build_conversion_plan([link], source, tmp_path / "output")


@pytest.mark.parametrize("output_name", ["source", "source/mirror"])
def test_overlapping_output_rejected_even_for_empty_source(
    tmp_path: Path, output_name: str
) -> None:
    source = tmp_path / "source"
    source.mkdir()

    result = run_conversion(source, tmp_path / output_name)

    assert result.exit_code != 0
    assert "must not overlap" in result.stderr


def test_dry_run_has_no_output_or_provenance_writes(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "intro.txt").write_text("content")
    output = tmp_path / "output"

    result = run_conversion(source, output, "--dry-run")

    assert result.exit_code == 0
    assert "Converted:  1" in result.stdout
    assert not output.exists()


@pytest.mark.parametrize("force", [False, True])
@pytest.mark.parametrize("first,second", [("note", "NOTE"), ("café", "cafe\u0301")])
def test_filesystem_aliases_are_preflighted_without_overwriting_outputs(
    tmp_path: Path, force: bool, first: str, second: str
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / f"{first}.md").write_text("markdown source")
    (source / f"{second}.txt").write_text("text source")
    output = tmp_path / "output"
    probe = tmp_path / f"{first}.probe"
    probe.write_text("filesystem probe")
    aliases = (tmp_path / f"{second}.probe").exists()
    probe.unlink()

    result = run_conversion(source, output, *(["--force"] if force else []))

    if aliases:
        assert result.exit_code != 0
        assert "Destination collision" in result.stderr
        assert not output.exists()
    else:
        assert result.exit_code == 0, result.stderr
        assert (output / f"{first}.md").read_text() == "markdown source"
        assert (output / f"{second}.md").read_text() == "text source"
        assert len(list(output.glob("*.md"))) == 2
    assert not list(tmp_path.glob(".trace-plan-*"))


def test_filesystem_alias_between_planned_file_and_directory_is_preflighted(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "note.txt").write_text("plain text")
    (source / "NOTE.md").mkdir()
    (source / "NOTE.md" / "nested.txt").write_text("nested source")
    probe = tmp_path / "note.probe"
    probe.write_text("filesystem probe")
    aliases = (tmp_path / "NOTE.probe").exists()
    probe.unlink()
    output = tmp_path / "output"

    result = run_conversion(source, output, "--force")

    if aliases:
        assert result.exit_code != 0
        assert "conflicts with a directory" in result.stderr
        assert not output.exists()
    else:
        assert result.exit_code == 0, result.stderr
        assert (output / "note.md").read_text() == "plain text"
        assert (output / "NOTE.md" / "nested.md").read_text() == "nested source"


@pytest.mark.parametrize("nested", [False, True])
def test_source_output_alias_overlap_is_rejected(tmp_path: Path, nested: bool) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "intro.md").write_text("source content")
    output = tmp_path / "SOURCE"
    aliases = output.exists() and output.samefile(source)
    if nested:
        output = output / "mirror"

    result = run_conversion(source, output, "--force")

    if aliases:
        assert result.exit_code != 0
        assert "must not overlap" in result.stderr
        assert not (source / "mirror").exists()
        assert not provenance_path(source / "intro.md").exists()
    else:
        assert result.exit_code == 0, result.stderr
        assert (output / "intro.md").read_text() == "source content"
    assert (source / "intro.md").read_text() == "source content"
