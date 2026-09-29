"""Multi-collection orchestration for Trace."""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from trace_search.config import settings
from trace_search.collections.diagnostics import (
    diagnose_collections,
    render_doctor_report,
)
from trace_search.collections.document_listing import list_documents_for_collections
from trace_search.collections.index_stats import render_index_stats
from trace_search.indexing.embeddings import EmbeddingBackend, build_embedding_backend
from trace_search.extraction.extractors import (
    SUPPORTED_EXTENSIONS,
    extract_content,
)
from trace_search.indexing.index_metadata import metadata_matches_settings
from trace_search.indexing.index_store import read_current, read_current_metadata
from trace_search.indexing.kb_paths import get_default_index_root, should_exclude_path
from trace_search.retrieval.search import (
    AdaptiveSearch,
    HybridSearch,
    KeywordSearch,
    SearchFilters,
    SemanticSearch,
)
from trace_search.retrieval.search_types import (
    AdaptiveSearchResult,
    SearchResult,
    SearchRoute,
)
from trace_search.server.server_warmup import warm_embedding_model
from trace_search.indexing.wiki_indexer import BackendProvider, WikiIndexer

logger = logging.getLogger(__name__)

DirectSearchMode = Literal["keyword", "semantic", "hybrid"]

# Standard RRF constant: dampens the gap between top ranks so one collection's
# rank-1 hit cannot dwarf another's rank-2 hit.
CROSS_COLLECTION_RRF_K = 60


@dataclass
class Collection:
    """A knowledge base collection with its own lazily opened index."""

    name: str
    kb_path: Path
    index_path: Path
    _indexer: WikiIndexer | None = field(default=None, repr=False)
    # Keeps two first queries from both opening the indexer or both building a
    # missing index. Searches themselves need no lock: each one reads one
    # immutable snapshot, and a reindex publishes a new snapshot atomically.
    _lock: threading.Lock = field(
        default_factory=threading.Lock, repr=False, compare=False
    )

    def indexer(
        self, backend: BackendProvider, *, build_if_missing: bool = True
    ) -> WikiIndexer:
        """Open the indexer; build the index first when none exists yet."""
        with self._lock:
            if self._indexer is None:
                self._indexer = WikiIndexer(
                    kb_path=self.kb_path,
                    index_root=self.index_path,
                    backend=backend,
                )
            if build_if_missing and not self._indexer.has_index():
                self._indexer.build_index()
            return self._indexer

    def search(
        self,
        mode: DirectSearchMode,
        query: str,
        top_k: int,
        filters: SearchFilters,
        backend: BackendProvider,
    ) -> list[SearchResult]:
        """Run one non-adaptive search mode for this collection."""
        indexer = self.indexer(backend)
        if mode == "keyword":
            return KeywordSearch(indexer).search(query, top_k, filters=filters)
        if mode == "semantic":
            return SemanticSearch(indexer).search(query, top_k, filters=filters)
        if mode == "hybrid":
            return HybridSearch(indexer).search(query, top_k, filters=filters)
        raise ValueError(f"Unknown search mode: {mode}")

    def search_adaptive(
        self,
        query: str,
        top_k: int,
        filters: SearchFilters | None,
        backend: BackendProvider,
        *,
        build_if_missing: bool = True,
    ) -> AdaptiveSearchResult:
        """Run adaptive search for this collection."""
        indexer = self.indexer(backend, build_if_missing=build_if_missing)
        return AdaptiveSearch(indexer).search(query, top_k, filters=filters)

    def get_neighbor_contents_batch(
        self,
        requests: list[tuple[str, int | None, int | None]],
        backend: BackendProvider,
    ) -> list[str | None]:
        """Batch-fetch neighbor content via the collection indexer."""
        return self.indexer(backend).neighbor_contents_batch(requests)

    def rebuild(self, backend: BackendProvider, *, force: bool = False) -> int:
        """Reindex this collection and return the resulting chunk count.

        Incremental by default; ``force=True`` rebuilds every file. Raises
        `IndexBusyError` when another process is already reindexing it.
        """
        return self.indexer(backend, build_if_missing=False).build_index(force=force)


class CollectionRegistry:
    """Manages multiple knowledge base collections with a shared embedding model."""

    def __init__(self, collections: dict[str, Path], index_root: Path | None = None):
        self._backend: EmbeddingBackend | None = None
        self._warmed: bool = False
        self._backend_lock = threading.Lock()
        idx_root = index_root or (settings.index_path if settings.index_path else None)
        self._index_root = idx_root

        self.collections: dict[str, Collection] = {}
        for name, kb_path in collections.items():
            col_index = get_default_index_root(
                kb_path, idx_root, name if idx_root else None
            )
            self.collections[name] = Collection(
                name=name,
                kb_path=kb_path,
                index_path=col_index,
            )

    @property
    def collection_names(self) -> list[str]:
        return sorted(self.collections.keys())

    def shared_backend(self) -> EmbeddingBackend:
        """The one embedding model all collections share, loaded on first use."""
        # Concurrent first queries would otherwise each load the model.
        with self._backend_lock:
            if self._backend is None:
                self._backend = build_embedding_backend()
                self._warm_backend()
            return self._backend

    def _warm_backend(self) -> None:
        """Warm the shared embedding backend exactly once per registry lifecycle."""
        if self._warmed:
            return
        assert self._backend is not None
        warm_embedding_model(self._backend)
        self._warmed = True

    def _resolve(self, collection: str | None) -> list[Collection]:
        """Resolve collection name to list of Collection objects."""
        if collection and collection.lower() != "all":
            col = self.collections.get(collection)
            if col is None:
                raise ValueError(
                    f"Unknown collection '{collection}'. "
                    f"Available: {', '.join(self.collection_names)}"
                )
            return [col]
        return list(self.collections.values())

    def _search(
        self,
        mode: DirectSearchMode,
        query: str,
        top_k: int,
        collection: str | None,
        filters: SearchFilters | None = None,
    ) -> list[SearchResult]:
        filters = filters or SearchFilters()
        cols = self._resolve(collection)

        if len(cols) == 1:
            return cols[0].search(mode, query, top_k, filters, self.shared_backend)
        return self._merge_results(
            [
                col.search(mode, query, top_k, filters, self.shared_backend)
                for col in cols
            ],
            top_k,
            [c.name for c in cols],
        )

    def search_keyword(
        self,
        query: str,
        top_k: int,
        collection: str | None,
        filters: SearchFilters | None = None,
    ) -> list[SearchResult]:
        return self._search("keyword", query, top_k, collection, filters)

    def search_semantic(
        self,
        query: str,
        top_k: int,
        collection: str | None,
        filters: SearchFilters | None = None,
    ) -> list[SearchResult]:
        return self._search("semantic", query, top_k, collection, filters)

    def search_hybrid(
        self,
        query: str,
        top_k: int,
        collection: str | None,
        filters: SearchFilters | None = None,
    ) -> list[SearchResult]:
        return self._search("hybrid", query, top_k, collection, filters)

    def search_adaptive(
        self,
        query: str,
        top_k: int,
        collection: str | None,
        filters: SearchFilters | None = None,
    ) -> AdaptiveSearchResult:
        filters = filters or SearchFilters()
        cols = self._resolve(collection)
        if len(cols) == 1:
            result = cols[0].search_adaptive(query, top_k, filters, self.shared_backend)
            hits = [self._with_neighbor_context(cols[0], hit) for hit in result.hits]
            return AdaptiveSearchResult(hits=hits, route=result.route)

        results = [
            c.search_adaptive(query, top_k, filters, self.shared_backend) for c in cols
        ]
        merged_hits = self._merge_results(
            [result.hits for result in results],
            top_k,
            [c.name for c in cols],
        )
        self._attach_neighbors_batched(merged_hits, cols)
        fallback_used = any(result.route.fallback_used for result in results)
        strategy = "hybrid" if fallback_used else "keyword"
        reasons = sorted({result.route.reason for result in results})
        return AdaptiveSearchResult(
            hits=merged_hits,
            route=SearchRoute(
                strategy=strategy,
                reason="; ".join(reasons),
                fallback_used=fallback_used,
                filters=filters,
            ),
        )

    def probe_search(
        self, query: str, top_k: int, collection: str | None
    ) -> list[SearchResult]:
        """Run a sample query only when indexes already exist and match settings."""
        cols = self._resolve(collection)
        missing = []
        incompatible = []
        for col in cols:
            if read_current(col.index_path) is None:
                missing.append(col.name)
                continue
            metadata = read_current_metadata(col.index_path)
            if metadata is None or not metadata_matches_settings(metadata):
                incompatible.append(col.name)
        if missing:
            names = ", ".join(sorted(missing))
            raise ValueError(
                f"Sample query skipped because indexes are missing for: {names}. "
                "Run `reindex` first."
            )
        if incompatible:
            names = ", ".join(sorted(incompatible))
            raise ValueError(
                f"Sample query skipped because indexes are incompatible or missing "
                f"metadata for: {names}. Run `reindex` first."
            )
        results = [
            c.search_adaptive(
                query, top_k, None, self.shared_backend, build_if_missing=False
            )
            for c in cols
        ]
        if len(cols) == 1:
            return results[0].hits
        return self._merge_results(
            [result.hits for result in results],
            top_k,
            [c.name for c in cols],
        )

    def _with_neighbor_context(
        self, col: Collection, hit: SearchResult
    ) -> SearchResult:
        enriched = hit.copy()
        if "neighbor_content" not in enriched:
            enriched["neighbor_content"] = col.get_neighbor_contents_batch(
                [
                    (
                        str(enriched.get("path", "")),
                        enriched.get("chunk_index"),
                        enriched.get("chunk_count"),
                    )
                ],
                self.shared_backend,
            )[0]
        return enriched

    def _attach_neighbors_batched(
        self, hits: list[SearchResult], cols: list[Collection]
    ) -> None:
        """Group `hits` by their `collection` tag and issue one batched neighbor
        fetch per collection. Mutates each hit in place to set `neighbor_content`.
        """
        col_by_name = {c.name: c for c in cols}
        by_collection: dict[str, list[SearchResult]] = defaultdict(list)
        for hit in hits:
            if "neighbor_content" in hit:
                continue
            col_name = hit.get("collection")
            if col_name in col_by_name:
                by_collection[col_name].append(hit)

        for col_name, col_hits in by_collection.items():
            col = col_by_name[col_name]
            requests = [
                (
                    str(h.get("path", "")),
                    h.get("chunk_index"),
                    h.get("chunk_count"),
                )
                for h in col_hits
            ]
            neighbors = col.get_neighbor_contents_batch(requests, self.shared_backend)
            for hit, neighbor in zip(col_hits, neighbors):
                hit["neighbor_content"] = neighbor

    @staticmethod
    def _merge_results(
        result_lists: list[list[SearchResult]],
        top_k: int,
        collection_names: list[str],
    ) -> list[SearchResult]:
        """Fuse results from multiple collections by per-collection rank (RRF).

        Raw scores are not comparable across independently indexed
        collections: BM25/IDF statistics depend on each corpus, and adaptive
        search can even return different score types per collection (raw BM25
        vs hybrid RRF). Ranks are comparable, so each hit is scored
        1/(k + rank) within its own collection and hits are interleaved by
        that fused score. Ties (equal rank) keep the given collection order.

        The fused score is stored on each hit as `fused_score` so downstream
        rendering (`format_search_context`) sorts by it instead of the raw
        per-collection scores.
        """
        fused: list[SearchResult] = []
        for results, name in zip(result_lists, collection_names):
            for rank, hit in enumerate(results, start=1):
                hit = hit.copy()
                hit["collection"] = name
                hit["fused_score"] = 1.0 / (CROSS_COLLECTION_RRF_K + rank)
                fused.append(hit)
        fused.sort(key=lambda h: float(h["fused_score"]), reverse=True)
        return fused[:top_k]

    def get_document(self, path: str, collection: str | None) -> str:
        cols = self._resolve(collection)
        for col in cols:
            kb = col.kb_path.resolve()
            doc_path = (kb / path).resolve()
            if not doc_path.is_relative_to(kb):
                logger.warning(
                    "get_document: rejected traversal attempt (path=%s, kb=%s)",
                    path,
                    kb,
                )
                continue
            if should_exclude_path(doc_path, kb):
                logger.warning(
                    "get_document: rejected excluded path (path=%s, kb=%s)",
                    path,
                    kb,
                )
                continue
            if doc_path.exists() and doc_path.is_file():
                try:
                    content = extract_content(doc_path)
                except ValueError as exc:
                    return f"Error: {exc}. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
                except Exception as exc:
                    logger.warning(
                        "get_document: extraction failed (path=%s, reason=%s)",
                        path,
                        exc,
                    )
                    return f"Error reading document: {path}"
                folder = path.split("/")[0] if "/" in path else ""
                col_label = (
                    f"**Collection:** {col.name}\n" if len(self.collections) > 1 else ""
                )
                return f"# {doc_path.stem}\n\n**Path:** `{path}`\n{col_label}**Folder:** {folder}\n\n---\n\n{content}\n"
        return f"Document not found: {path}"

    def list_documents(
        self,
        folder: str | None,
        limit: int,
        collection: str | None,
        filters: SearchFilters | None = None,
    ) -> str:
        filters = filters or SearchFilters()
        cols = self._resolve(collection)
        return list_documents_for_collections(
            [(col.name, col.kb_path) for col in cols],
            folder=folder,
            limit=limit,
            filters=filters,
        )

    def reindex(self, collection: str | None, force: bool = False) -> str:
        """Reindex the given collection(s); incremental by default."""
        cols = self._resolve(collection)
        results = []
        for col in cols:
            chunks = col.rebuild(self.shared_backend, force=force)
            suffix = " (forced rebuild)" if force else ""
            results.append(f"**{col.name}**: {chunks} chunks indexed{suffix}")
        return "Reindex complete.\n\n" + "\n".join(results)

    def doctor(
        self,
        sample_query: str | None = None,
        collection: str | None = None,
    ) -> str:
        """Run Trace diagnostics for configuration, corpus, indexes, and queries."""
        report = diagnose_collections(
            {name: col.kb_path for name, col in self.collections.items()},
            index_root=self._index_root,
            sample_query=sample_query,
            sample_collection=collection,
            sample_query_runner=lambda query, col_name: self.probe_search(
                query,
                5,
                col_name,
            ),
        )
        return render_doctor_report(report)

    def index_stats(self, collection: str | None) -> str:
        cols = self._resolve(collection)
        collection_stats = [
            (
                col.name,
                col.indexer(self.shared_backend, build_if_missing=False).get_stats(),
            )
            for col in cols
        ]
        return render_index_stats(collection_stats, SemanticSearch.get_cache_stats())
