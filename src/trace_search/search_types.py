"""Search result types shared across retrieval and formatting."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _empty_filters():
    from trace_search.search import SearchFilters

    return SearchFilters()


@dataclass(frozen=True)
class SearchRoute:
    """Routing metadata for smart search."""

    strategy: str
    reason: str
    fallback_used: bool
    filters: Any = field(default_factory=_empty_filters)


@dataclass(frozen=True)
class SmartSearchResult:
    """Smart search hits plus transparent routing metadata."""

    hits: list[dict[str, Any]]
    route: SearchRoute
