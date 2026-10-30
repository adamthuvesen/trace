"""Trace - semantic, keyword, and hybrid search over local knowledge bases."""

from importlib.metadata import PackageNotFoundError, version

from trace_search.collections.collection_registry import (
    CollectionRegistry as CollectionRegistry,
)
from trace_search.config import settings as settings
from trace_search.indexing.wiki_indexer import WikiIndexer as WikiIndexer
from trace_search.retrieval.formatting import (
    format_results as format_results,
    format_search_context as format_search_context,
)
from trace_search.retrieval.search import (
    AdaptiveSearch as AdaptiveSearch,
    HybridSearch as HybridSearch,
    KeywordSearch as KeywordSearch,
    SemanticSearch as SemanticSearch,
)
from trace_search.retrieval.search_types import (
    ChunkRef as ChunkRef,
    DocumentRef as DocumentRef,
    SearchHit as SearchHit,
    SearchResponse as SearchResponse,
    SearchFilters as SearchFilters,
)

try:
    __version__ = version("trace")
except PackageNotFoundError:
    __version__ = "0+unknown"

__all__ = [
    "settings",
    "WikiIndexer",
    "SemanticSearch",
    "KeywordSearch",
    "HybridSearch",
    "AdaptiveSearch",
    "format_results",
    "format_search_context",
    "CollectionRegistry",
    "DocumentRef",
    "ChunkRef",
    "SearchHit",
    "SearchResponse",
    "SearchFilters",
]
