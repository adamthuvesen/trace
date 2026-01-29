"""Trace - semantic, keyword, and hybrid search over local knowledge bases."""

__version__ = "0.3.0"

from trace_search.config import settings
from trace_search.indexer import WikiIndexer
from trace_search.search import (
    SemanticSearch,
    KeywordSearch,
    HybridSearch,
    format_results,
)

from trace_search.server_app import CollectionRegistry

__all__ = [
    "settings",
    "WikiIndexer",
    "SemanticSearch",
    "KeywordSearch",
    "HybridSearch",
    "format_results",
    "CollectionRegistry",
]
