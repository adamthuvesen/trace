"""Construct normalized search hits from retrieval backends."""

from __future__ import annotations

from typing import Any

from trace_search.indexing.index_paths import chunk_id
from trace_search.retrieval.models import SearchHit


def hit_from_chroma(
    doc_id: str,
    metadata: dict[str, Any],
    content: str,
    similarity: float,
) -> SearchHit:
    """Build a semantic hit from a Chroma query result row."""
    return SearchHit(
        id=doc_id,
        path=str(metadata["path"]),
        title=str(metadata["title"]),
        folder=str(metadata["folder"]),
        chunk_index=metadata.get("chunk_index"),
        chunk_count=metadata.get("chunk_count"),
        breadcrumb=metadata.get("breadcrumb"),
        extension=metadata.get("extension"),
        source_mtime=(
            float(metadata["source_mtime"])
            if metadata.get("source_mtime") is not None
            else None
        ),
        content=content,
        score=similarity,
        source="semantic",
    )


def hit_from_bm25(
    metadata: dict[str, Any],
    content: str,
    score: float,
) -> SearchHit:
    """Build a keyword hit from BM25 corpus metadata."""
    path = str(metadata["path"])
    chunk_index = metadata.get("chunk_index")
    hit_id = chunk_id(path, int(chunk_index)) if chunk_index is not None else path
    return SearchHit(
        id=hit_id,
        path=path,
        title=str(metadata["title"]),
        folder=str(metadata["folder"]),
        chunk_index=chunk_index,
        chunk_count=metadata.get("chunk_count"),
        breadcrumb=metadata.get("breadcrumb"),
        extension=metadata.get("extension"),
        source_mtime=(
            float(metadata["source_mtime"])
            if metadata.get("source_mtime") is not None
            else None
        ),
        content=content,
        score=score,
        source="keyword",
    )


def hits_to_dicts(hits: list[SearchHit]) -> list[dict[str, Any]]:
    """Serialize hits for MCP callers."""
    return [hit.to_dict() for hit in hits]
