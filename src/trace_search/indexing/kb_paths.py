"""Knowledge-base path helpers."""

from __future__ import annotations

from pathlib import Path

from trace_search.config import settings


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
    return any(
        part.startswith(".") or part in exclude
        for part in _relative_parts(kb_path, path)
    )


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
