"""Search result types shared across retrieval and formatting."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, TypeAlias

SearchResult: TypeAlias = dict[str, Any]


class RouteFilters(Protocol):
    @property
    def path_prefix(self) -> tuple[str, ...]: ...

    @property
    def extensions(self) -> tuple[str, ...]: ...

    @property
    def since(self) -> datetime | None: ...

    @property
    def is_empty(self) -> bool: ...

    def describe(self) -> str: ...


def _empty_filters() -> RouteFilters:
    from trace_search.retrieval.search import SearchFilters

    return SearchFilters()


@dataclass(frozen=True)
class SearchRoute:
    """Routing metadata for adaptive search."""

    strategy: str
    reason: str
    fallback_used: bool
    filters: RouteFilters = field(default_factory=_empty_filters)


@dataclass(frozen=True)
class AdaptiveSearchResult:
    """Adaptive search hits plus transparent routing metadata."""

    hits: list[SearchResult]
    route: SearchRoute
