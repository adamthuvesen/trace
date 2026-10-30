"""Build search hits from indexed chunks."""

from __future__ import annotations

from trace_search.indexing.index_store import ChunkMetadata
from trace_search.retrieval.search_types import (
    ScoreEvidence,
    SearchHit,
    SearchSource,
)


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
