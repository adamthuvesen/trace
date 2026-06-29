"""Shared Trace operations used by CLI and MCP adapters."""

from __future__ import annotations

from trace_search.config import get_settings
from trace_search.retrieval.formatting import format_context_packets, format_results
from trace_search.retrieval.search import SearchFilters, parse_filters
from trace_search.collections.collection_registry import CollectionRegistry


def _build_filters(
    path_prefix: str | list[str] | None,
    extensions: str | list[str] | None,
    since: str | None,
) -> SearchFilters:
    """Parse user-supplied filter inputs into a `SearchFilters` instance."""
    return parse_filters(
        path_prefix=path_prefix,
        extensions=extensions,
        since=since,
    )


class TraceOperations:
    """Text-returning operations exposed by Trace adapters."""

    def __init__(self, registry: CollectionRegistry):
        self.registry = registry

    @classmethod
    def from_settings(cls) -> "TraceOperations":
        app_settings = get_settings()
        registry = CollectionRegistry(
            app_settings.parsed_collections,
            index_root=app_settings.index_path,
        )
        return cls(registry)

    def search(
        self,
        query: str,
        top_k: int = 10,
        collection: str | None = None,
        path_prefix: str | list[str] | None = None,
        extensions: str | list[str] | None = None,
        since: str | None = None,
    ) -> str:
        filters = _build_filters(path_prefix, extensions, since)
        result = self.registry.search_adaptive(
            query, top_k, collection, filters=filters
        )
        return format_context_packets(result.hits, query=query, route=result.route)

    def semantic_search(
        self,
        query: str,
        top_k: int = 10,
        collection: str | None = None,
        path_prefix: str | list[str] | None = None,
        extensions: str | list[str] | None = None,
        since: str | None = None,
    ) -> str:
        filters = _build_filters(path_prefix, extensions, since)
        results = self.registry.search_semantic(
            query, top_k, collection, filters=filters
        )
        return format_results(results)

    def keyword_search(
        self,
        keyword: str,
        max_results: int = 20,
        collection: str | None = None,
        path_prefix: str | list[str] | None = None,
        extensions: str | list[str] | None = None,
        since: str | None = None,
    ) -> str:
        filters = _build_filters(path_prefix, extensions, since)
        results = self.registry.search_keyword(
            keyword, max_results, collection, filters=filters
        )
        return format_results(results)

    def search_hybrid(
        self,
        query: str,
        top_k: int = 10,
        collection: str | None = None,
        path_prefix: str | list[str] | None = None,
        extensions: str | list[str] | None = None,
        since: str | None = None,
    ) -> str:
        filters = _build_filters(path_prefix, extensions, since)
        results = self.registry.search_hybrid(query, top_k, collection, filters=filters)
        return format_results(results)

    def get_document(self, path: str, collection: str | None = None) -> str:
        return self.registry.get_document(path, collection)

    def list_documents(
        self,
        folder: str | None = None,
        limit: int = 50,
        collection: str | None = None,
        path_prefix: str | list[str] | None = None,
        extensions: str | list[str] | None = None,
        since: str | None = None,
    ) -> str:
        filters = _build_filters(path_prefix, extensions, since)
        return self.registry.list_documents(folder, limit, collection, filters=filters)

    def index_stats(self, collection: str | None = None) -> str:
        return self.registry.index_stats(collection)

    def reindex(self, collection: str | None = None, force: bool = False) -> str:
        return self.registry.reindex(collection, force=force)

    def doctor(
        self,
        sample_query: str | None = None,
        collection: str | None = None,
    ) -> str:
        return self.registry.doctor(
            sample_query=sample_query,
            collection=collection,
        )
