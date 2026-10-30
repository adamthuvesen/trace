"""Shared Trace operations used by CLI and MCP adapters."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Literal

from trace_search.config import get_settings
from trace_search.collections.diagnostics import (
    DoctorReport,
    diagnose_collections,
    render_doctor_report,
)
from trace_search.collections.document_listing import list_documents_for_collections
from trace_search.collections.index_stats import render_index_stats
from trace_search.collections.errors import (
    DocumentNotFoundError,
    DocumentReadError,
    OperationError,
    ReindexError,
)
from trace_search.extraction.extractors import extract_content
from trace_search.indexing.index_metadata import metadata_query_compatible
from trace_search.indexing.kb_paths import actual_path_spelling, should_exclude_path
from trace_search.retrieval.search import (
    AdaptiveSearch,
    HybridSearch,
    KeywordSearch,
    SemanticSearch,
)
from trace_search.retrieval.search_types import SearchHit, SearchResponse, SearchRoute
from trace_search.retrieval.formatting import format_results, format_search_context
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


logger = logging.getLogger(__name__)


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
            config=app_settings,
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
        response = self.search_response("adaptive", query, top_k, collection, filters)
        return format_search_context(response, query=query, max_documents=top_k)

    def semantic_search(
        self,
        query: str,
        top_k: int = 10,
        collection: str | None = None,
        path_prefix: str | list[str] | None = None,
        extensions: str | list[str] | None = None,
        since: str | None = None,
    ) -> str:
        _validate_limit(top_k)
        filters = _build_filters(path_prefix, extensions, since)
        results = self.search_response("semantic", query, top_k, collection, filters)
        return format_results(results.hits)

    def keyword_search(
        self,
        keyword: str,
        max_results: int = 20,
        collection: str | None = None,
        path_prefix: str | list[str] | None = None,
        extensions: str | list[str] | None = None,
        since: str | None = None,
    ) -> str:
        _validate_limit(max_results)
        filters = _build_filters(path_prefix, extensions, since)
        results = self.search_response(
            "keyword", keyword, max_results, collection, filters
        )
        return format_results(results.hits)

    def search_hybrid(
        self,
        query: str,
        top_k: int = 10,
        collection: str | None = None,
        path_prefix: str | list[str] | None = None,
        extensions: str | list[str] | None = None,
        since: str | None = None,
    ) -> str:
        _validate_limit(top_k)
        filters = _build_filters(path_prefix, extensions, since)
        results = self.search_response("hybrid", query, top_k, collection, filters)
        return format_results(results.hits)

    def get_document(self, path: str, collection: str | None = None) -> str:
        for col in self.registry._resolve(collection):
            kb = col.kb_path.resolve()
            requested_path = kb / path
            doc_path = requested_path.resolve()
            if doc_path.is_relative_to(kb):
                requested_path = actual_path_spelling(requested_path, kb)
            if not doc_path.is_relative_to(kb) or should_exclude_path(
                requested_path, kb, self.registry.config.exclude_patterns_list
            ):
                logger.warning(
                    "get_document: rejected traversal or excluded path (path=%s, kb=%s)",
                    path,
                    kb,
                )
                continue
            if doc_path.is_file():
                try:
                    content = extract_content(doc_path)
                except Exception as exc:
                    logger.warning(
                        "get_document: extraction failed (path=%s, reason=%s)",
                        path,
                        exc,
                    )
                    raise DocumentReadError(
                        f"Error reading document {path}: {exc}"
                    ) from exc
                folder = path.split("/")[0] if "/" in path else ""
                label = (
                    f"**Collection:** {col.name}\n"
                    if len(self.registry.collections) > 1
                    else ""
                )
                return f"# {doc_path.stem}\n\n**Path:** `{path}`\n{label}**Folder:** {folder}\n\n---\n\n{content}\n"
        raise DocumentNotFoundError(f"Document not found: {path}")

    def list_documents(
        self,
        folder: str | None = None,
        limit: int = 50,
        collection: str | None = None,
        path_prefix: str | list[str] | None = None,
        extensions: str | list[str] | None = None,
        since: str | None = None,
    ) -> str:
        _validate_limit(limit, maximum=500)
        return list_documents_for_collections(
            [(col.name, col.kb_path) for col in self.registry._resolve(collection)],
            folder=folder,
            limit=limit,
            filters=_build_filters(path_prefix, extensions, since),
            config=self.registry.config,
        )

    def index_stats(self, collection: str | None = None) -> str:
        collection_stats = [
            (
                col.name,
                col.indexer(
                    self.registry.shared_backend, build_if_missing=False
                ).get_stats(),
            )
            for col in self.registry._resolve(collection)
        ]
        return render_index_stats(
            collection_stats, SemanticSearch.get_cache_stats(), self.registry.config
        )

    def reindex(self, collection: str | None = None, force: bool = False) -> str:
        completed: list[tuple[str, int]] = []
        failed: list[tuple[str, str]] = []
        for col in self.registry._resolve(collection):
            try:
                completed.append(
                    (col.name, col.rebuild(self.registry.shared_backend, force=force))
                )
            except Exception as exc:
                failed.append((col.name, str(exc)))
        if failed:
            raise ReindexError(tuple(completed), tuple(failed))
        suffix = " (forced rebuild)" if force else ""
        return "Reindex complete.\n\n" + "\n".join(
            f"**{name}**: {count} chunks indexed{suffix}" for name, count in completed
        )

    def doctor(
        self,
        sample_query: str | None = None,
        collection: str | None = None,
    ) -> str:
        return render_doctor_report(self.doctor_report(sample_query, collection))

    def search_response(
        self,
        mode: Literal["adaptive", "keyword", "semantic", "hybrid"],
        query: str,
        limit: int = 10,
        collection: str | None = None,
        filters: SearchFilters | None = None,
        *,
        build_if_missing: bool = True,
    ) -> SearchResponse:
        """Resolve resources once and retain one generation through the complete search."""
        _validate_limit(limit)
        filters = filters or SearchFilters()
        results: list[SearchResponse] = []
        for col in self.registry._resolve(collection):
            indexer = col.indexer(
                self.registry.shared_backend, build_if_missing=build_if_missing
            )
            snapshot = indexer.snapshot()
            if not build_if_missing:
                if snapshot.generation is None:
                    raise OperationError(
                        f"Sample query skipped because indexes are missing for: {col.name}. Run `reindex` first."
                    )
                if snapshot.metadata is None or not metadata_query_compatible(
                    snapshot.metadata, self.registry.config, indexer.backend
                ):
                    raise OperationError(
                        f"Sample query skipped because indexes are incompatible or missing metadata for: {col.name}. Run `reindex` first."
                    )
            if mode == "adaptive":
                response = AdaptiveSearch(indexer).search(
                    query, limit, filters, snapshot
                )
            elif mode == "keyword":
                response = SearchResponse(
                    tuple(
                        KeywordSearch(indexer).search(query, limit, filters, snapshot)
                    )
                )
            elif mode == "semantic":
                response = SearchResponse(
                    tuple(
                        SemanticSearch(indexer).search(query, limit, filters, snapshot)
                    )
                )
            else:
                response = SearchResponse(
                    tuple(
                        HybridSearch(indexer).search(
                            query, limit, filters=filters, snapshot=snapshot
                        )
                    )
                )
            hits = [hit.in_collection(col.name) for hit in response.hits]
            if mode == "adaptive":
                neighbors = indexer.neighbor_contents_batch(
                    [
                        (hit.path, hit.ref.chunk_index, hit.metadata["chunk_count"])
                        for hit in hits
                    ],
                    snapshot=snapshot,
                )
                hits = [
                    replace(hit, neighbor_content=neighbor)
                    for hit, neighbor in zip(hits, neighbors, strict=True)
                ]
            results.append(SearchResponse(tuple(hits), response.route))
        if len(results) == 1:
            return results[0]
        merged: list[SearchHit] = []
        for response in results:
            merged.extend(
                replace(
                    hit, evidence=replace(hit.evidence, fused_score=1.0 / (60 + rank))
                )
                for rank, hit in enumerate(response.hits, 1)
            )
        merged.sort(key=lambda hit: hit.evidence.fused_score or 0, reverse=True)
        route = None
        if mode == "adaptive":
            routes = [
                response.route for response in results if response.route is not None
            ]
            fallback = any(route.fallback_used for route in routes)
            route = SearchRoute(
                "hybrid" if fallback else "keyword",
                "; ".join(sorted({route.reason for route in routes})),
                fallback,
                filters,
            )
        return SearchResponse(tuple(merged[:limit]), route)

    def doctor_report(
        self, sample_query: str | None = None, collection: str | None = None
    ) -> DoctorReport:
        cols = self.registry._resolve(collection)
        return diagnose_collections(
            {col.name: col.kb_path for col in cols},
            index_root=self.registry._index_root,
            config=self.registry.config,
            sample_query=sample_query,
            sample_collection=collection,
            sample_query_runner=lambda query, name: (
                self.search_response(
                    "adaptive", query, 5, name, build_if_missing=False
                ).hits
            ),
        )


def _validate_limit(value: int, maximum: int = 100) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= maximum
    ):
        raise ValueError(f"Result limit must be between 1 and {maximum}")
