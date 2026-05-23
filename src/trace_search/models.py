"""Shared data models for search results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Legacy alias for gradual migration away from untyped dict hits.
HitDict = dict[str, Any]


@dataclass
class SearchHit:
    """Normalized search result record."""

    id: str
    path: str
    title: str
    folder: str
    content: str
    score: float
    source: str
    chunk_index: int | None = None
    chunk_count: int | None = None
    breadcrumb: str | None = None
    extension: str | None = None
    source_mtime: float | None = None
    rerank_score: float | None = None
    rrf_score: float | None = None
    match_hints: list[str] | None = None
    collection: str | None = None

    def to_dict(self) -> HitDict:
        """Serialize to the dict shape used by MCP tools and eval."""
        data: HitDict = {
            "id": self.id,
            "path": self.path,
            "title": self.title,
            "folder": self.folder,
            "content": self.content,
            "score": self.score,
            "source": self.source,
        }
        if self.chunk_index is not None:
            data["chunk_index"] = self.chunk_index
        if self.chunk_count is not None:
            data["chunk_count"] = self.chunk_count
        if self.breadcrumb is not None:
            data["breadcrumb"] = self.breadcrumb
        if self.extension is not None:
            data["extension"] = self.extension
        if self.source_mtime is not None:
            data["source_mtime"] = self.source_mtime
        if self.rerank_score is not None:
            data["rerank_score"] = self.rerank_score
        if self.rrf_score is not None:
            data["rrf_score"] = self.rrf_score
        if self.match_hints is not None:
            data["match_hints"] = self.match_hints
        if self.collection is not None:
            data["collection"] = self.collection
        return data

    @classmethod
    def from_dict(cls, data: HitDict) -> SearchHit:
        """Build a SearchHit from a legacy result dict."""
        return cls(
            id=str(data["id"]),
            path=str(data["path"]),
            title=str(data.get("title", "")),
            folder=str(data.get("folder", "")),
            content=str(data.get("content", "")),
            score=float(data.get("score", 0.0)),
            source=str(data.get("source", "")),
            chunk_index=data.get("chunk_index"),
            chunk_count=data.get("chunk_count"),
            breadcrumb=data.get("breadcrumb"),
            extension=data.get("extension"),
            source_mtime=(
                float(data["source_mtime"])
                if data.get("source_mtime") is not None
                else None
            ),
            rerank_score=(
                float(data["rerank_score"])
                if data.get("rerank_score") is not None
                else None
            ),
            rrf_score=(
                float(data["rrf_score"]) if data.get("rrf_score") is not None else None
            ),
            match_hints=data.get("match_hints"),
            collection=data.get("collection"),
        )
