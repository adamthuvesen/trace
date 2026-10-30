"""Shared knowledge-base file iteration."""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from pathlib import Path

from trace_search.extraction.extractors import SUPPORTED_EXTENSIONS
from trace_search.config import get_settings
from trace_search.indexing.kb_paths import (
    is_traceignored_directory,
    should_exclude_path,
)


def iter_kb_files(
    kb_path: Path,
    *,
    root: Path | None = None,
    exclude_patterns: list[str] | None = None,
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

    if not stat.S_ISDIR(search_root.stat().st_mode):
        return
    exclusions = (
        exclude_patterns
        if exclude_patterns is not None
        else get_settings().exclude_patterns_list
    )

    def walk(directory: Path) -> Iterator[Path]:
        with os.scandir(directory) as entries:
            children = sorted(entries, key=lambda entry: entry.name)
        for entry in children:
            file_path = Path(entry.path)
            if entry.name.startswith(".") or entry.name in exclusions:
                continue
            if entry.is_dir(follow_symlinks=False):
                if not is_traceignored_directory(file_path, kb_resolved):
                    yield from walk(file_path)
            elif file_path.suffix.lower() in SUPPORTED_EXTENSIONS and entry.is_file():
                if not should_exclude_path(file_path, kb_resolved, exclusions):
                    yield file_path

    if search_root != kb_resolved and (
        should_exclude_path(search_root, kb_resolved, exclusions)
        or is_traceignored_directory(search_root, kb_resolved)
    ):
        return
    yield from walk(search_root)
