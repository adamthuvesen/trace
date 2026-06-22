"""Trace - semantic, keyword, and hybrid search over local knowledge bases."""

__version__ = "0.3.0"

from trace_search.config import settings  # noqa: F401

__all__ = [
    "settings",
    "WikiIndexer",
    "SemanticSearch",
    "KeywordSearch",
    "HybridSearch",
    "SmartSearch",
    "format_results",
    "format_context_packets",
    "CollectionRegistry",
]


def __getattr__(name: str):
    """Lazily expose runtime classes without making package import heavy."""
    if name == "WikiIndexer":
        from trace_search.indexing.wiki_indexer import WikiIndexer

        return WikiIndexer
    if name in {
        "SemanticSearch",
        "KeywordSearch",
        "HybridSearch",
        "SmartSearch",
        "format_results",
        "format_context_packets",
    }:
        from trace_search.retrieval import search

        return getattr(search, name)
    if name == "CollectionRegistry":
        from trace_search.collections.collection_registry import CollectionRegistry

        return CollectionRegistry
    raise AttributeError(f"module 'trace_search' has no attribute {name!r}")
