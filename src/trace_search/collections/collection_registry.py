"""Multi-collection orchestration for Trace."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from trace_search.config import Settings, get_settings
from trace_search.collections.diagnostics import (
    render_doctor_report,
)
from trace_search.collections.index_stats import render_index_stats
from trace_search.indexing.embeddings import EmbeddingBackend, build_embedding_backend
from trace_search.indexing.kb_paths import get_default_index_root
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
)
from trace_search.indexing.embedding_warmup import warm_embedding_model
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
    config: Settings = field(default_factory=get_settings, repr=False)
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
                    config=self.config,
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

    def __init__(
        self,
        collections: dict[str, Path],
        index_root: Path | None = None,
        *,
        config: Settings | None = None,
    ):
        self.config = (config or get_settings()).model_copy(deep=True)
        self._backend: EmbeddingBackend | None = None
        self._warmed: bool = False
        self._backend_lock = threading.Lock()
        idx_root = index_root if index_root is not None else self.config.index_path
        self._index_root = idx_root

        self.collections: dict[str, Collection] = {}
        if not collections:
            raise ValueError("At least one collection is required")
        for name, kb_path in collections.items():
            if (
                not name
                or name.lower() == "all"
                or name in {".", ".."}
                or any(part in name for part in ("/", "\\", "\0"))
            ):
                raise ValueError(f"Invalid collection name: {name!r}")
            kb_path = Path(kb_path).expanduser().resolve()
            if not kb_path.is_dir():
                raise ValueError(
                    f"Collection '{name}' path is not a directory: {kb_path}"
                )
            col_index = get_default_index_root(
                kb_path, idx_root, name if idx_root else None
            )
            self.collections[name] = Collection(
                name=name,
                kb_path=kb_path,
                index_path=col_index,
                config=self.config,
            )

    @property
    def collection_names(self) -> list[str]:
        return sorted(self.collections.keys())

    def shared_backend(self) -> EmbeddingBackend:
        """The one embedding model all collections share, loaded on first use."""
        # Concurrent first queries would otherwise each load the model.
        with self._backend_lock:
            if self._backend is None:
                self._backend = build_embedding_backend(self.config)
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
        from trace_search.collections.operations import TraceOperations

        return (
            TraceOperations(self)
            .search_response(mode, query, top_k, collection, filters)
            .legacy_hits()
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
        from trace_search.collections.operations import TraceOperations

        response = TraceOperations(self).search_response(
            "adaptive", query, top_k, collection, filters
        )
        assert response.route is not None
        return AdaptiveSearchResult(response.legacy_hits(), response.route)

    def probe_search(
        self, query: str, top_k: int, collection: str | None
    ) -> list[SearchResult]:
        from trace_search.collections.operations import TraceOperations

        return (
            TraceOperations(self)
            .search_response(
                "adaptive", query, top_k, collection, build_if_missing=False
            )
            .legacy_hits()
        )

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
        from trace_search.collections.operations import TraceOperations

        return TraceOperations(self).get_document(path, collection)

    def list_documents(
        self,
        folder: str | None,
        limit: int,
        collection: str | None,
        filters: SearchFilters | None = None,
    ) -> str:
        from trace_search.collections.operations import TraceOperations

        from trace_search.collections.document_listing import _normalize_limit

        return TraceOperations(self).document_listing(
            folder, _normalize_limit(limit), collection, filters
        )

    def reindex(self, collection: str | None, force: bool = False) -> str:
        from trace_search.collections.operations import TraceOperations

        return TraceOperations(self).build_collections(collection, force)

    def doctor(
        self, sample_query: str | None = None, collection: str | None = None
    ) -> str:
        from trace_search.collections.operations import TraceOperations

        return render_doctor_report(
            TraceOperations(self).doctor_report(sample_query, collection)
        )

    def index_stats(self, collection: str | None) -> str:
        cols = self._resolve(collection)
        collection_stats = [
            (
                col.name,
                col.indexer(self.shared_backend, build_if_missing=False).get_stats(),
            )
            for col in cols
        ]
        return render_index_stats(
            collection_stats, SemanticSearch.get_cache_stats(), self.config
        )
