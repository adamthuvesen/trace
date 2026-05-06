"""Shared Trace operations used by CLI and MCP adapters."""

from __future__ import annotations

from trace_search.config import get_settings
from trace_search.search import format_results, format_smart_search
from trace_search.server_app import CollectionRegistry


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
    ) -> str:
        result = self.registry.search_smart(query, top_k, collection)
        return format_smart_search(result, query)

    def semantic_search(
        self,
        query: str,
        top_k: int = 10,
        collection: str | None = None,
    ) -> str:
        results = self.registry.search_semantic(query, top_k, collection)
        return format_results(results)

    def keyword_search(
        self,
        keyword: str,
        max_results: int = 20,
        collection: str | None = None,
    ) -> str:
        results = self.registry.search_keyword(keyword, max_results, collection)
        return format_results(results)

    def search_hybrid(
        self,
        query: str,
        top_k: int = 10,
        collection: str | None = None,
    ) -> str:
        results = self.registry.search_hybrid(query, top_k, collection)
        return format_results(results)

    def get_document(self, path: str, collection: str | None = None) -> str:
        return self.registry.get_document(path, collection)

    def list_documents(
        self,
        folder: str | None = None,
        limit: int = 50,
        collection: str | None = None,
    ) -> str:
        return self.registry.list_documents(folder, limit, collection)

    def index_stats(self, collection: str | None = None) -> str:
        return self.registry.index_stats(collection)

    def reindex(self, collection: str | None = None) -> str:
        return self.registry.reindex(collection)

    def doctor(
        self,
        sample_query: str | None = None,
        collection: str | None = None,
    ) -> str:
        return self.registry.doctor(
            sample_query=sample_query,
            collection=collection,
        )
