"""Shared data models for search results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the dict shape used by MCP tools and eval."""
        data: dict[str, Any] = {
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
