"""Typed retrieval identities, evidence, filters, and ordered responses."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Literal, cast

from trace_search.indexing.index_store import (
    ChunkMetadata,
)

type SearchSource = Literal["keyword", "semantic", "hybrid", "unknown"]


@dataclass(frozen=True)
class SearchFilters:
    """Optional scope filters applied across all search modes.

    Filters are evaluated before ranking as a row mask over the index snapshot:
    BM25 receives it as a weight mask and vector search skips masked rows. The
    empty `SearchFilters()` is a no-op.
    """

    path_prefix: tuple[str, ...] = ()
    extensions: tuple[str, ...] = ()
    since: datetime | None = None

    @property
    def is_empty(self) -> bool:
        return not self.path_prefix and not self.extensions and self.since is None

    def describe(self) -> str:
        """Human-readable summary of active filters; empty string if none."""
        parts: list[str] = []
        if self.path_prefix:
            joined = ", ".join(self.path_prefix)
            parts.append(f"path_prefix={joined}")
        if self.extensions:
            parts.append(f"extensions={', '.join(self.extensions)}")
        if self.since is not None:
            parts.append(f"since={self.since.isoformat()}")
        return "; ".join(parts)

    def matches_record(
        self,
        rel_path: str,
        extension: str,
        mtime: float | None,
    ) -> bool:
        """Return whether a file or hit record satisfies all active filters."""
        if self.is_empty:
            return True
        if self.path_prefix and not any(rel_path.startswith(prefix) for prefix in self.path_prefix):
            return False
        if self.extensions and extension not in self.extensions:
            return False
        if self.since is not None:
            since_epoch = self.since.timestamp()
            if mtime is None or mtime < since_epoch:
                return False
        return True


def _normalize_extension(value: str) -> str:
    """Lowercase and ensure leading dot. Raises ValueError on empty input."""
    cleaned = value.strip().lower()
    if not cleaned:
        raise ValueError("Extension must be non-empty, e.g. '.md'")
    return cleaned if cleaned.startswith(".") else f".{cleaned}"


def _split_extensions(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """Normalize extension lists, allowing comma-separated entries per item."""
    normalized: list[str] = []
    for value in values:
        normalized.extend(_normalize_extension(item) for item in value.split(","))
    return tuple(normalized)


def _parse_path_prefixes(
    path_prefix: str | list[str] | tuple[str, ...] | None,
) -> tuple[str, ...]:
    if path_prefix is None or path_prefix == "":
        return ()
    if isinstance(path_prefix, str):
        return (path_prefix,)
    return tuple(prefix for prefix in path_prefix if prefix)


def _parse_extensions(
    extensions: str | list[str] | tuple[str, ...] | None,
) -> tuple[str, ...]:
    if extensions is None or extensions == "":
        return ()
    if isinstance(extensions, str):
        return _split_extensions((extensions,))
    return _split_extensions(extensions)


def _parse_since(since: str | datetime | None) -> datetime | None:
    if since is None or since == "":
        return None

    if isinstance(since, datetime):
        parsed_since = since
    elif isinstance(since, str):
        try:
            parsed_since = datetime.fromisoformat(since)
        except ValueError as exc:
            raise ValueError(
                f"Invalid `since` value {since!r}: expected ISO 8601 "
                "datetime (e.g. 2026-01-01T00:00:00Z)"
            ) from exc
    else:
        raise ValueError(
            f"Invalid `since` value: expected ISO 8601 string or datetime, "
            f"got {type(since).__name__}"
        )

    if parsed_since.tzinfo is None:
        return parsed_since.replace(tzinfo=UTC)
    return parsed_since


def parse_filters(
    path_prefix: str | list[str] | tuple[str, ...] | None = None,
    extensions: str | list[str] | tuple[str, ...] | None = None,
    since: str | datetime | None = None,
) -> SearchFilters:
    """Normalize and validate filter inputs.

    - `path_prefix` accepts a string or a list/tuple of strings.
    - `extensions` accepts a list/tuple, or a comma-separated string for CLI use.
      Entries are lowercased and gain a leading dot if missing.
    - `since` accepts an ISO 8601 datetime string or a `datetime`. Naive
      datetimes are assumed to be UTC. Invalid input raises ``ValueError``.
    """
    return SearchFilters(
        path_prefix=_parse_path_prefixes(path_prefix),
        extensions=_parse_extensions(extensions),
        since=_parse_since(since),
    )


@dataclass(frozen=True)
class DocumentRef:
    collection: str
    path: str


@dataclass(frozen=True)
class ChunkRef:
    document: DocumentRef
    generation: str | None
    chunk_index: int


@dataclass(frozen=True)
class ScoreEvidence:
    score: float = 0.0
    semantic_score: float | None = None
    lexical_boost: float | None = None
    bm25_chunk_score: float | None = None
    bm25_file_score: float | None = None
    bm25_file_support: int | None = None
    bm25_metadata_overlap: float | None = None
    rrf_score: float | None = None
    fused_score: float | None = None


@dataclass(frozen=True)
class SearchHit:
    metadata: ChunkMetadata
    content: str
    source: SearchSource
    evidence: ScoreEvidence
    generation: str | None = None
    collection: str = ""
    match_hints: tuple[str, ...] = ()
    neighbor_content: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "metadata", cast(ChunkMetadata, MappingProxyType(dict(self.metadata)))
        )

    @property
    def ref(self) -> ChunkRef:
        return ChunkRef(
            DocumentRef(self.collection, self.path),
            self.generation,
            self.metadata["chunk_index"],
        )

    @property
    def path(self) -> str:
        return self.metadata["path"]

    def in_collection(self, name: str) -> SearchHit:
        return replace(self, collection=name)


@dataclass(frozen=True)
class SearchRoute:
    strategy: str
    reason: str
    fallback_used: bool
    filters: SearchFilters = field(default_factory=SearchFilters)


@dataclass(frozen=True)
class SearchResponse:
    """Hits in final ranking order. Renderers must preserve this order."""

    hits: tuple[SearchHit, ...]
    route: SearchRoute | None = None
