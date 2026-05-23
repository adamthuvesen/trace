"""Shared knowledge-base file iteration."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from trace_search.extractors import SUPPORTED_EXTENSIONS
from trace_search.kb_paths import should_exclude_path


def iter_kb_files(
    kb_path: Path,
    *,
    root: Path | None = None,
) -> Iterator[Path]:
    """Yield supported, non-excluded files under a knowledge base.

    When ``root`` is set, only files under that directory (must be inside
    ``kb_path``) are considered. Used by indexing, metadata, diagnostics,
    and document listing.
    """
    kb_resolved = kb_path.resolve()
    search_root = root.resolve() if root is not None else kb_resolved
    if not search_root.is_relative_to(kb_resolved):
        return

    for file_path in search_root.rglob("*"):
        if not file_path.is_file():
            continue
        ext = file_path.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            continue
        if should_exclude_path(file_path, kb_resolved):
            continue
        yield file_path
