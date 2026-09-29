"""Knowledge-base path helpers."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pathspec import GitIgnoreSpec

from trace_search.config import settings

TRACEIGNORE_FILENAME = ".traceignore"


def _relative_parts(kb_path: Path, path: Path) -> tuple[str, ...]:
    """Return path parts relative to the KB root, resolving only when needed."""
    try:
        return path.relative_to(kb_path).parts
    except ValueError:
        return path.resolve().relative_to(kb_path.resolve()).parts


def _is_within_root(path: Path, root: Path) -> bool:
    """Return whether the resolved path stays under the resolved root."""
    try:
        return path.resolve().is_relative_to(root.resolve())
    except OSError:
        return False


@lru_cache(maxsize=32)
def _parse_traceignore(ignore_file: Path, mtime_ns: int) -> GitIgnoreSpec:
    """Parse an ignore file; ``mtime_ns`` is part of the key so edits reload."""
    lines = ignore_file.read_text(encoding="utf-8").splitlines()
    return GitIgnoreSpec.from_lines(lines)


def load_traceignore(kb_path: Path) -> GitIgnoreSpec | None:
    """Return the KB root's ``.traceignore`` spec, or None when there is none."""
    ignore_file = kb_path / TRACEIGNORE_FILENAME
    try:
        mtime_ns = ignore_file.stat().st_mtime_ns
    except FileNotFoundError:
        return None
    return _parse_traceignore(ignore_file, mtime_ns)


def is_traceignored(path: Path, kb_path: Path) -> bool:
    """Return whether the KB's ``.traceignore`` (gitignore semantics) skips path."""
    spec = load_traceignore(kb_path)
    if spec is None:
        return False
    return spec.match_file("/".join(_relative_parts(kb_path, path)))


def should_exclude_path(
    path: Path,
    kb_path: Path,
    exclude_patterns: list[str] | None = None,
) -> bool:
    """Return whether a KB-relative path should be skipped."""
    if not _is_within_root(path, kb_path):
        return True
    exclude = set(
        exclude_patterns
        if exclude_patterns is not None
        else settings.exclude_patterns_list
    )
    if any(
        part.startswith(".") or part in exclude
        for part in _relative_parts(kb_path, path)
    ):
        return True
    return is_traceignored(path, kb_path)


def get_default_index_root(
    kb_path: Path,
    index_root: Path | None = None,
    collection_name: str | None = None,
) -> Path:
    """Resolve the root directory that contains model-specific indexes."""
    if index_root is None:
        return kb_path / ".mcp-search" / "indexes"
    if collection_name:
        return index_root / collection_name
    return index_root
