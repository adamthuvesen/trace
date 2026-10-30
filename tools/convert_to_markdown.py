#!/usr/bin/env python3
"""Convert source documents to a verified markdown mirror.

Install conversion dependencies with ``uv sync --extra convert``.
Run with ``uv run python tools/convert_to_markdown.py --help``.
"""

from __future__ import annotations

import csv
import hashlib
import os
import shutil
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

import click
from pydantic import BaseModel, ConfigDict, ValidationError
from rich.console import Console

from trace_search.filesystem_paths import validate_distinct_targets

console = Console()
CONVERTER_VERSION = 1
ConversionStatus = Literal["converted", "copied", "unchanged", "unverified", "failed"]


@dataclass
class ConversionStats:
    converted: int = 0
    copied: int = 0
    unchanged: int = 0
    unverified: int = 0
    failed: int = 0
    errors: list[tuple[Path, str]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.converted + self.copied + self.unchanged + self.unverified + self.failed


@dataclass(frozen=True)
class PlannedConversion:
    source_path: Path
    destination_path: Path
    source_sha256: str
    extension: str


@dataclass(frozen=True)
class ConversionPlan:
    source_root: Path
    output_root: Path
    files: tuple[PlannedConversion, ...]


class ConversionProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: int
    source_path: str
    source_sha256: str
    output_sha256: str


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".csv", ".xlsx", ".md", ".txt"}
EXCLUDE_PATTERNS = {
    "node_modules",
    ".venv",
    "__pycache__",
    ".next",
    ".git",
    "dbt_packages",
    ".mcp-search",
    ".chroma_db",
    ".bm25_index",
}


def convert_with_markitdown(input_path: Path, output_path: Path) -> None:
    from markitdown import MarkItDown

    result = MarkItDown().convert(str(input_path))
    output_path.write_text(result.text_content, encoding="utf-8")


def convert_csv_to_markdown(input_path: Path, output_path: Path) -> None:
    import pandas as pd

    # Pandas can infer an index from excess fields, silently discarding their meaning.
    with input_path.open(encoding="utf-8", newline="") as source:
        rows = csv.reader(source, strict=True)
        header = next(rows, None)
        if not header:
            raise ValueError("CSV must contain a nonempty header")
        for row in rows:
            if row and len(row) != len(header):
                raise ValueError(
                    f"Malformed CSV at line {rows.line_num}: expected "
                    f"{len(header)} fields, found {len(row)}"
                )
    frame = pd.read_csv(input_path, encoding="utf-8", on_bad_lines="error")
    markdown = f"# {input_path.stem}\n\n{frame.to_markdown(index=False)}"
    output_path.write_text(markdown, encoding="utf-8")


def convert_excel_to_markdown(input_path: Path, output_path: Path) -> None:
    import pandas as pd

    sheets = pd.read_excel(input_path, sheet_name=None)
    parts = [f"# {input_path.stem}\n"]
    for sheet_name, frame in sheets.items():
        parts.append(f"\n## {sheet_name}\n\n{frame.to_markdown(index=False)}")
    output_path.write_text("\n".join(parts), encoding="utf-8")


def copy_file(input_path: Path, output_path: Path) -> None:
    shutil.copy2(input_path, output_path)


def copy_as_markdown(input_path: Path, output_path: Path) -> None:
    output_path.write_text(input_path.read_text(encoding="utf-8"), encoding="utf-8")


CONVERTERS: dict[str, Callable[[Path, Path], None]] = {
    ".pdf": convert_with_markitdown,
    ".docx": convert_with_markitdown,
    ".pptx": convert_with_markitdown,
    ".csv": convert_csv_to_markdown,
    ".xlsx": convert_excel_to_markdown,
    ".md": copy_file,
    ".txt": copy_as_markdown,
}


def should_exclude(path: Path, wiki_path: Path) -> bool:
    rel_parts = path.relative_to(wiki_path).parts
    if any(part.startswith(".") or part in EXCLUDE_PATTERNS for part in rel_parts):
        return True
    try:
        return not path.resolve().is_relative_to(wiki_path.resolve())
    except OSError:
        return True


def collect_files(
    wiki_path: Path,
    types_filter: set[str] | None = None,
) -> list[Path]:
    files: list[Path] = []
    for path in wiki_path.rglob("*"):
        if not path.is_file() or should_exclude(path, wiki_path):
            continue
        extension = path.suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            continue
        if types_filter and extension.lstrip(".") not in types_filter:
            continue
        files.append(path)
    return sorted(files)


def get_output_path(input_path: Path, wiki_path: Path, output_dir: Path) -> Path:
    relative = input_path.relative_to(wiki_path)
    output_path = output_dir / relative
    if output_path.suffix.lower() != ".md":
        output_path = output_path.with_suffix(".md")
    return output_path


def fingerprint(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def provenance_path(destination: Path) -> Path:
    return destination.with_name(f".{destination.name}.trace-conversion.json")


def validate_destination(destination: Path, output_root: Path) -> None:
    if not destination.is_relative_to(output_root):
        raise ValueError(f"Destination is outside the output directory: {destination}")
    if not destination.resolve().is_relative_to(output_root):
        raise ValueError(f"Destination symlink escapes the output directory: {destination}")
    for path in (destination, *destination.parents):
        if path == output_root:
            break
        if path.is_symlink():
            raise ValueError(f"Destination contains a symlink: {path}")
        if path.exists() and (path.is_dir() if path == destination else not path.is_dir()):
            raise ValueError(f"Destination has an incompatible existing path: {path}")


def build_conversion_plan(
    files: list[Path], source_root: Path, output_root: Path
) -> ConversionPlan:
    source_root = source_root.expanduser().resolve()
    output_root = output_root.expanduser().resolve()
    if not source_root.is_dir():
        raise ValueError(f"Source path must be a directory: {source_root}")
    source_inside_output = output_root.exists() and any(
        path.samefile(output_root) for path in (source_root, *source_root.parents)
    )
    output_inside_source = any(
        path.exists() and path.samefile(source_root) for path in (output_root, *output_root.parents)
    )
    if source_inside_output or output_inside_source:
        raise ValueError("Source and output directories must not overlap")
    if output_root.exists() and not output_root.is_dir():
        raise ValueError(f"Output path must be a directory: {output_root}")

    planned: list[PlannedConversion] = []
    destinations: dict[Path, Path] = {}
    for input_path in files:
        lexical_source = input_path.absolute()
        resolved_source = input_path.resolve(strict=True)
        if not resolved_source.is_relative_to(source_root):
            raise ValueError(f"Source symlink escapes the source directory: {input_path}")
        destination = get_output_path(lexical_source, source_root, output_root)
        validate_destination(destination, output_root)
        validate_destination(provenance_path(destination), output_root)
        if destination in destinations:
            raise ValueError(
                f"Destination collision: {destinations[destination]} and {input_path} "
                f"both map to {destination}"
            )
        destinations[destination] = input_path
        extension = input_path.suffix.lower()
        if extension not in CONVERTERS:
            raise ValueError(f"No converter for {input_path}")
        planned.append(
            PlannedConversion(resolved_source, destination, fingerprint(resolved_source), extension)
        )
    for destination in destinations:
        if any(parent in destinations for parent in destination.parents):
            raise ValueError(f"Destination file conflicts with a directory: {destination}")
    validate_filesystem_destinations(planned)
    return ConversionPlan(source_root, output_root, tuple(planned))


def validate_filesystem_destinations(entries: list[PlannedConversion]) -> None:
    validate_distinct_targets(
        [
            (str(entry.source_path), target)
            for entry in entries
            for target in (
                entry.destination_path,
                provenance_path(entry.destination_path),
            )
        ]
    )


def existing_status(entry: PlannedConversion, force: bool) -> ConversionStatus | None:
    if force or not entry.destination_path.exists():
        return None
    try:
        provenance = ConversionProvenance.model_validate_json(
            provenance_path(entry.destination_path).read_text(encoding="utf-8")
        )
    except OSError, UnicodeError, ValidationError:
        return "unverified"
    if provenance.source_path != str(entry.source_path) or provenance.output_sha256 != fingerprint(
        entry.destination_path
    ):
        return "unverified"
    if provenance.version == CONVERTER_VERSION and provenance.source_sha256 == entry.source_sha256:
        return "unchanged"
    return None


def convert_file(
    entry: PlannedConversion,
    plan: ConversionPlan,
    force: bool = False,
    dry_run: bool = False,
) -> tuple[ConversionStatus, str | None]:
    destination = entry.destination_path
    try:
        validate_destination(destination, plan.output_root)
        validate_destination(provenance_path(destination), plan.output_root)
        status = existing_status(entry, force)
        if status == "unverified":
            return (
                status,
                f"Unverified output: {destination}. Use --force to regenerate.",
            )
        if status == "unchanged":
            return status, None
        success: ConversionStatus = "copied" if entry.extension == ".md" else "converted"
        if dry_run:
            return success, None
        if not entry.source_path.resolve(strict=True).is_relative_to(plan.source_root):
            raise ValueError(f"Source escapes the source directory: {entry.source_path}")
        if fingerprint(entry.source_path) != entry.source_sha256:
            raise ValueError("Source changed after planning. Run the conversion again.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".trace-convert-", dir=destination.parent) as name:
            staging = Path(name)
            temporary_output = staging / destination.name
            CONVERTERS[entry.extension](entry.source_path, temporary_output)
            if fingerprint(entry.source_path) != entry.source_sha256:
                raise ValueError("Source changed during conversion. Run it again.")
            provenance = ConversionProvenance(
                version=CONVERTER_VERSION,
                source_path=str(entry.source_path),
                source_sha256=entry.source_sha256,
                output_sha256=fingerprint(temporary_output),
            )
            temporary_provenance = staging / "provenance.json"
            temporary_provenance.write_text(provenance.model_dump_json(), encoding="utf-8")
            validate_destination(destination, plan.output_root)
            validate_destination(provenance_path(destination), plan.output_root)
            backup = staging / "previous-output"
            had_output = destination.exists()
            if had_output:
                shutil.copy2(destination, backup)
            Path(temporary_output).replace(destination)
            try:
                Path(temporary_provenance).replace(provenance_path(destination))
            except OSError:
                if had_output:
                    Path(backup).replace(destination)
                else:
                    destination.unlink()
                raise
        return success, None
    except Exception as error:
        return "failed", str(error)


def process_files(
    files: list[Path],
    wiki_path: Path,
    output_dir: Path,
    force: bool,
    dry_run: bool,
) -> ConversionStats:
    plan = build_conversion_plan(files, wiki_path, output_dir)
    stats = ConversionStats()
    for entry in plan.files:
        status, error = convert_file(entry, plan, force, dry_run)
        if status == "converted":
            stats.converted += 1
        elif status == "copied":
            stats.copied += 1
        elif status == "unchanged":
            stats.unchanged += 1
        elif status == "unverified":
            stats.unverified += 1
        else:
            stats.failed += 1
        if error:
            stats.errors.append((entry.source_path, error))
    return stats


@click.command()
@click.option(
    "--source-path",
    type=click.Path(path_type=Path),
    default=None,
    help="Source directory (default: CONVERT_SOURCE_PATH or ./docs-source)",
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Output directory (default: CONVERT_MARKDOWN_OUT or ./markdown-out)",
)
@click.option("--dry-run", is_flag=True, help="Preview without converting")
@click.option("--force", is_flag=True, help="Regenerate outputs, including unverified files")
@click.option("--types", type=str, default=None, help="Comma-separated types (e.g., pdf,docx)")
def main(
    source_path: Path | None,
    output_dir: Path | None,
    dry_run: bool,
    force: bool,
    types: str | None,
) -> None:
    """Convert source documents to a verified markdown mirror."""
    source_path = (
        (source_path or Path(os.environ.get("CONVERT_SOURCE_PATH", "docs-source")))
        .expanduser()
        .resolve()
    )
    output_dir = (
        (output_dir or Path(os.environ.get("CONVERT_MARKDOWN_OUT", "markdown-out")))
        .expanduser()
        .resolve()
    )
    if not source_path.is_dir():
        raise click.UsageError(f"Source path must be a directory: {source_path}")
    types_filter = None
    if types:
        types_filter = {item.strip().lower().lstrip(".") for item in types.split(",")}
        invalid = types_filter - {extension.lstrip(".") for extension in SUPPORTED_EXTENSIONS}
        if invalid:
            raise click.UsageError(f"Unsupported file types: {', '.join(sorted(invalid))}")
    console.print(f"Source path: {source_path}", markup=False)
    console.print(f"Output dir: {output_dir}", markup=False)
    if dry_run:
        console.print("DRY RUN: no files will be modified")
    try:
        files = collect_files(source_path, types_filter)
        stats = process_files(files, source_path, output_dir, force, dry_run)
    except (OSError, ValueError) as planning_error:
        raise click.ClickException(str(planning_error)) from planning_error
    by_extension = Counter(path.suffix.lower() for path in files)
    console.print(f"Found {len(files)} files: {dict(by_extension)}", markup=False)
    console.print("Summary:")
    console.print(f"  Converted:  {stats.converted}")
    console.print(f"  Copied:     {stats.copied}")
    console.print(f"  Unchanged:  {stats.unchanged}")
    console.print(f"  Unverified: {stats.unverified}")
    console.print(f"  Failed:     {stats.failed}")
    for path, error in stats.errors:
        click.echo(f"{path}: {error}", err=True)
    if stats.failed or stats.unverified:
        raise click.ClickException(
            f"Conversion incomplete: {stats.failed} failed, {stats.unverified} unverified. "
            "Resolve the errors above and retry."
        )


if __name__ == "__main__":
    main()
