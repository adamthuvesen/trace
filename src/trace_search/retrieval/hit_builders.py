"""Build search hits from indexed chunks."""

from __future__ import annotations

from typing import Any

from trace_search.retrieval.search_types import (
    SearchHit,
    ScoreEvidence,
    SearchSource,
)

from trace_search.indexing.index_store import ChunkMetadata


def chunk_hit(
    chunk: ChunkMetadata, content: str, score: float, source: SearchSource
) -> dict[str, Any]:
    """Compatibility dictionary for a typed indexed hit."""
    return typed_chunk_hit(chunk, content, score, source, None).to_dict()


def typed_chunk_hit(
    chunk: ChunkMetadata,
    content: str,
    score: float,
    source: SearchSource,
    generation: str | None,
) -> SearchHit:
    return SearchHit(
        metadata=chunk,
        content=content,
        source=source,
        evidence=ScoreEvidence(score),
        generation=generation,
    )
