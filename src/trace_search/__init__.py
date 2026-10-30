"""Trace - semantic, keyword, and hybrid search over local knowledge bases."""

from importlib.metadata import PackageNotFoundError, version

from trace_search.collections.collection_registry import (
    CollectionRegistry as CollectionRegistry,
)
from trace_search.config import settings as settings
from trace_search.indexing.wiki_indexer import WikiIndexer as WikiIndexer
from trace_search.retrieval.formatting import (
    format_results as format_results,
)
from trace_search.retrieval.formatting import (
    format_search_context as format_search_context,
)
from trace_search.retrieval.search import (
    AdaptiveSearch as AdaptiveSearch,
)
from trace_search.retrieval.search import (
    HybridSearch as HybridSearch,
)
from trace_search.retrieval.search import (
    KeywordSearch as KeywordSearch,
)
from trace_search.retrieval.search import (
    SemanticSearch as SemanticSearch,
)
from trace_search.retrieval.search_types import (
    ChunkRef as ChunkRef,
)
from trace_search.retrieval.search_types import (
    DocumentRef as DocumentRef,
)
from trace_search.retrieval.search_types import (
    SearchFilters as SearchFilters,
)
from trace_search.retrieval.search_types import (
    SearchHit as SearchHit,
)
from trace_search.retrieval.search_types import (
    SearchResponse as SearchResponse,
)

try:
    __version__ = version("trace")
except PackageNotFoundError:
    __version__ = "0+unknown"

__all__ = [
    "AdaptiveSearch",
    "ChunkRef",
    "CollectionRegistry",
    "DocumentRef",
    "HybridSearch",
    "KeywordSearch",
    "SearchFilters",
    "SearchHit",
    "SearchResponse",
    "SemanticSearch",
    "WikiIndexer",
    "format_results",
    "format_search_context",
    "settings",
]
