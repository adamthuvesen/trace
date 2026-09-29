"""Build search hits from indexed chunks."""

from __future__ import annotations

from typing import Any

from trace_search.indexing.index_paths import chunk_id
from trace_search.indexing.index_store import ChunkMetadata

# Frontmatter-derived fields ride along only when the page set them.
_OPTIONAL_FIELDS = ("aliases", "status", "as_of")


def chunk_hit(
    chunk: ChunkMetadata, content: str, score: float, source: str
) -> dict[str, Any]:
    """Return the hit dict that search modes, fusion, and formatting share."""
    hit: dict[str, Any] = {
        "id": chunk_id(chunk["path"], chunk["chunk_index"]),
        "path": chunk["path"],
        "title": chunk["title"],
        "folder": chunk["folder"],
        "content": content,
        "score": score,
        "source": source,
        "chunk_index": chunk["chunk_index"],
        "chunk_count": chunk["chunk_count"],
        "breadcrumb": chunk["breadcrumb"],
        "extension": chunk["extension"],
        "source_mtime": chunk["source_mtime"],
    }
    for name in _OPTIONAL_FIELDS:
        if value := chunk.get(name):
            hit[name] = value
    return hit
