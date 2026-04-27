#!/usr/bin/env python3
"""Convert wiki files to a markdown-only mirror.

Creates a clean markdown copy of your knowledge base at .markdown/,
converting PDFs, Office docs, and spreadsheets while copying existing
markdown files.

Usage:
    uv pip install -e ".[convert]"
    uv run python tools/convert_to_markdown.py --dry-run
    uv run python tools/convert_to_markdown.py
"""

from __future__ import annotations

from collections import Counter
import logging
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import click
from rich.console import Console
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)
console = Console()


@dataclass
class ConversionStats:
    converted: int = 0
    copied: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[tuple[Path, str]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.converted + self.copied + self.skipped + self.failed


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".csv", ".xlsx", ".md", ".txt"}
SKIP_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".avif",
    ".mov",
    ".mp4",
}

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

    md = MarkItDown()
    result = md.convert(str(input_path))
    output_path.write_text(result.text_content, encoding="utf-8")


def convert_csv_to_markdown(input_path: Path, output_path: Path) -> None:
    import pandas as pd

    df = pd.read_csv(input_path, encoding="utf-8", on_bad_lines="skip")
    markdown = f"# {input_path.stem}\n\n{df.to_markdown(index=False)}"
    output_path.write_text(markdown, encoding="utf-8")


def convert_excel_to_markdown(input_path: Path, output_path: Path) -> None:
    """One section per sheet."""
    import pandas as pd

    sheets = pd.read_excel(input_path, sheet_name=None)
    parts = [f"# {input_path.stem}\n"]

    for sheet_name, df in sheets.items():
        parts.append(f"\n## {sheet_name}\n\n{df.to_markdown(index=False)}")

    output_path.write_text("\n".join(parts), encoding="utf-8")


def copy_file(input_path: Path, output_path: Path) -> None:
    shutil.copy2(input_path, output_path)


def copy_as_markdown(input_path: Path, output_path: Path) -> None:
    content = input_path.read_text(encoding="utf-8", errors="replace")
    output_path.write_text(content, encoding="utf-8")


CONVERTERS: dict[str, Callable[[Path, Path], None]] = {
    ".pdf": convert_with_markitdown,
    ".docx": convert_with_markitdown,
    ".pptx": convert_with_markitdown,
    ".csv": convert_csv_to_markdown,
    ".xlsx": convert_excel_to_markdown,
    ".md": copy_file,
    ".txt": copy_as_markdown,
}


def should_exclude(path: Path) -> bool:
    return any(part.startswith(".") or part in EXCLUDE_PATTERNS for part in path.parts)


def collect_files(
    wiki_path: Path,
    types_filter: set[str] | None = None,
) -> list[Path]:
    files = []

    for path in wiki_path.rglob("*"):
        if not path.is_file():
            continue

        if should_exclude(path):
            continue

        ext = path.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            continue

        if types_filter and ext.lstrip(".") not in types_filter:
            continue

        files.append(path)

    return sorted(files)


def get_output_path(input_path: Path, wiki_path: Path, output_dir: Path) -> Path:
    """Preserve directory structure under output_dir."""
    relative = input_path.relative_to(wiki_path)
    output_path = output_dir / relative

    if output_path.suffix.lower() != ".md":
        output_path = output_path.with_suffix(".md")

    return output_path


def convert_file(
    input_path: Path,
    output_path: Path,
    force: bool = False,
) -> tuple[str, str | None]:
    """
    Convert a single file.

    Returns:
        Tuple of (status, error_message).
        Status is one of: "converted", "copied", "skipped", "failed"
    """
    ext = input_path.suffix.lower()

    if output_path.exists() and not force:
        return "skipped", None

    converter = CONVERTERS.get(ext)
    if not converter:
        return "skipped", f"No converter for {ext}"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        converter(input_path, output_path)
        status = "copied" if ext == ".md" else "converted"
        return status, None
    except Exception as e:
        return "failed", str(e)


def process_files(
    files: list[Path],
    wiki_path: Path,
    output_dir: Path,
    force: bool,
    dry_run: bool,
) -> ConversionStats:
    stats = ConversionStats()

    if dry_run:
        for input_path in files:
            output_path = get_output_path(input_path, wiki_path, output_dir)
            ext = input_path.suffix.lower()

            if output_path.exists() and not force:
                stats.skipped += 1
            elif ext == ".md":
                stats.copied += 1
            else:
                stats.converted += 1

        return stats

    # Process files sequentially (parallel causes recursion issues with marker/markitdown)
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("[progress.percentage]{task.fields[current_file]}"),
        console=console,
    ) as progress:
        task = progress.add_task(
            "Converting files...", total=len(files), current_file=""
        )

        for input_path in files:
            output_path = get_output_path(input_path, wiki_path, output_dir)
            display_name = (
                input_path.name[:40] + "..."
                if len(input_path.name) > 40
                else input_path.name
            )
            progress.update(task, current_file=display_name)

            status, error = convert_file(input_path, output_path, force)

            if status == "converted":
                stats.converted += 1
            elif status == "copied":
                stats.copied += 1
            elif status == "skipped":
                stats.skipped += 1
            elif status == "failed":
                stats.failed += 1
                stats.errors.append((input_path, error or "Unknown error"))

            progress.advance(task)

    return stats


def write_error_log(output_dir: Path, errors: list[tuple[Path, str]]) -> None:
    log_path = output_dir / ".errors.log"
    with log_path.open("w", encoding="utf-8") as f:
        f.write("# Conversion Errors\n\n")
        for path, error in errors:
            f.write(f"## {path}\n{error}\n\n")


@click.command()
@click.option(
    "--wiki-path",
    type=click.Path(path_type=Path),
    default=None,
    help="Wiki directory (default: WIKI_EXPORT_PATH or ./wiki-source)",
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Output directory (default: WIKI_MARKDOWN_OUT or ./wiki-markdown-out)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Preview without converting",
)
@click.option(
    "--force",
    is_flag=True,
    help="Reconvert existing files",
)
@click.option(
    "--types",
    type=str,
    default=None,
    help="Comma-separated file types (e.g., pdf,docx)",
)
def main(
    wiki_path: Path | None,
    output_dir: Path | None,
    dry_run: bool,
    force: bool,
    types: str | None,
) -> None:
    """Convert wiki files to a markdown-only mirror."""
    wiki_path = (
        wiki_path
        or Path(os.environ.get("WIKI_EXPORT_PATH", "wiki-source")).expanduser()
    ).resolve()
    output_dir = (
        output_dir
        or Path(os.environ.get("WIKI_MARKDOWN_OUT", "wiki-markdown-out")).expanduser()
    ).resolve()
    if not wiki_path.exists():
        raise click.UsageError(f"Wiki path does not exist: {wiki_path}")

    types_filter = None
    if types:
        types_filter = {t.strip().lower().lstrip(".") for t in types.split(",")}

    console.print(f"\n[bold]Wiki path:[/bold] {wiki_path}")
    console.print(f"[bold]Output dir:[/bold] {output_dir}")

    if types_filter:
        console.print(f"[bold]Types:[/bold] {', '.join(sorted(types_filter))}")

    if dry_run:
        console.print("[yellow]DRY RUN - no files will be modified[/yellow]\n")

    console.print("\nScanning for files...")
    files = collect_files(wiki_path, types_filter)

    if not files:
        console.print("[yellow]No files found to convert.[/yellow]")
        sys.exit(0)

    by_ext = Counter(path.suffix.lower() for path in files)

    console.print(f"\n[bold]Found {len(files)} files:[/bold]")
    for ext, count in by_ext.most_common():
        console.print(f"  {ext}: {count}")

    console.print()

    stats = process_files(files, wiki_path, output_dir, force, dry_run)

    console.print("\n[bold]Summary:[/bold]")
    console.print(f"  Converted: {stats.converted}")
    console.print(f"  Copied:    {stats.copied}")
    console.print(f"  Skipped:   {stats.skipped}")
    if stats.failed:
        console.print(f"  [red]Failed:    {stats.failed}[/red]")

    if stats.errors and not dry_run:
        write_error_log(output_dir, stats.errors)
        console.print(f"\n[yellow]Errors logged to: {output_dir}/.errors.log[/yellow]")

    if not dry_run and stats.converted + stats.copied > 0:
        console.print(
            f"\n[green]Done![/green] Markdown mirror created at: {output_dir}"
        )
        console.print("\nTo use with search, set:")
        console.print(f"  KB_PATH={output_dir}")


if __name__ == "__main__":
    main()
