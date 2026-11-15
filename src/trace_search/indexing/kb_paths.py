from __future__ import annotations

from pathlib import Path


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
