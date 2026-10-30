"""Build `SearchHit` test values from flat field names."""

from __future__ import annotations

from dataclasses import fields
from typing import Any, cast

from trace_search.indexing.index_store import ChunkMetadata
from trace_search.retrieval.search_types import ScoreEvidence, SearchHit, SearchSource

_EVIDENCE = {item.name for item in fields(ScoreEvidence)}
_HIT = {"content", "source", "generation", "collection", "match_hints"}


def make_hit(path: str, **values: Any) -> SearchHit:
    metadata = {
        "path": path,
        "title": "",
        "folder": "",
        "chunk_index": 0,
        "chunk_count": 1,
        "breadcrumb": "",
        "extension": "",
        "source_mtime": 0.0,
    }
    metadata.update(
        (key, value)
        for key, value in values.items()
        if key not in _EVIDENCE | _HIT | {"id", "neighbor_content"}
    )
    return SearchHit(
        metadata=cast(ChunkMetadata, metadata),
        content=values.get("content", ""),
        source=cast(SearchSource, values.get("source", "unknown")),
        evidence=ScoreEvidence(**{k: v for k, v in values.items() if k in _EVIDENCE}),
        generation=values.get("generation"),
        collection=values.get("collection", ""),
        match_hints=tuple(values.get("match_hints", ())),
        neighbor_content=values.get("neighbor_content"),
    )
