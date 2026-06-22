"""Search implementations for wiki knowledge base."""

from __future__ import annotations

import heapq
import logging
import re
from collections import OrderedDict, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path as _Path
from typing import TYPE_CHECKING, Any, ClassVar, Protocol

from sentence_transformers import CrossEncoder

from trace_search.retrieval.bm25_tokenize import tokenize_keywords
from trace_search.config import settings
from trace_search.indexing.embeddings import EmbeddingBackend, build_embedding_backend
from trace_search.retrieval.hit_builders import hit_from_bm25, hit_from_chroma, hits_to_dicts
from trace_search.retrieval.formatting import (  # noqa: F401 — package re-exports
    format_context_packets,
    format_results,
)
from trace_search.retrieval.query_profile import (
    BM25_DOMINANCE_MARGIN,
    BM25_DECISIVE_TOP_MARGIN,
    BM25_STRONG_HIT_FRACTION,
    BM25_WEAK_BEST_SCORE,
    SMART_KEYWORD_STRENGTH_TOP_K,
    classify_query,
    is_conceptual_query,
)
from trace_search.retrieval.search_types import SearchRoute, SmartSearchResult

if TYPE_CHECKING:
    from trace_search.indexing.wiki_indexer import WikiIndexer

logger = logging.getLogger(__name__)

# Cap how many candidates a single retrieval call may over-fetch when filters
# are active. Keeps per-query latency bounded even on very large corpora.
_FILTER_OVERSAMPLE = 5
_MAX_OVERSAMPLE_FETCH = 500
_SEMANTIC_OVERSAMPLE = 1
_SEMANTIC_MAX_CANDIDATES = 50
_SEMANTIC_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "for",
        "how",
        "in",
        "is",
        "of",
        "the",
        "to",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
    }
)


def _clamp_top_k(top_k: int, default: int = 10, max_val: int = 100) -> int:
    """Clamp top_k to valid range [1, max_val]."""
    if top_k < 1:
        return default
    return min(top_k, max_val)


@dataclass(frozen=True)
class SearchFilters:
    """Optional scope filters applied across all search modes.

    Filters are evaluated pre-ranking: vector and metadata-aware stores push
    them down at fetch time; BM25 over-fetches and applies them to candidates
    before truncation. The empty `SearchFilters()` is a no-op.
    """

    path_prefix: tuple[str, ...] = ()
    extensions: tuple[str, ...] = ()
    since: datetime | None = None

    @property
    def is_empty(self) -> bool:
        return not self.path_prefix and not self.extensions and self.since is None

    def describe(self) -> str:
        """Human-readable summary of active filters; empty string if none."""
        parts: list[str] = []
        if self.path_prefix:
            joined = ", ".join(self.path_prefix)
            parts.append(f"path_prefix={joined}")
        if self.extensions:
            parts.append(f"extensions={', '.join(self.extensions)}")
        if self.since is not None:
            parts.append(f"since={self.since.isoformat()}")
        return "; ".join(parts)

    def matches_record(
        self,
        rel_path: str,
        extension: str,
        mtime: float | None,
    ) -> bool:
        """Return whether a file or hit record satisfies all active filters."""
        if self.is_empty:
            return True
        if self.path_prefix and not any(
            rel_path.startswith(prefix) for prefix in self.path_prefix
        ):
            return False
        if self.extensions and extension not in self.extensions:
            return False
        if self.since is not None:
            since_epoch = self.since.timestamp()
            if mtime is None or mtime < since_epoch:
                return False
        return True


def _normalize_extension(value: str) -> str:
    """Lowercase and ensure leading dot. Raises ValueError on empty input."""
    cleaned = value.strip().lower()
    if not cleaned:
        raise ValueError("Extension must be non-empty, e.g. '.md'")
    return cleaned if cleaned.startswith(".") else f".{cleaned}"


def _split_extensions(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """Normalize extension lists, allowing comma-separated entries per item."""
    normalized: list[str] = []
    for value in values:
        normalized.extend(_normalize_extension(item) for item in value.split(","))
    return tuple(normalized)


def parse_filters(
    path_prefix: str | list[str] | tuple[str, ...] | None = None,
    extensions: str | list[str] | tuple[str, ...] | None = None,
    since: str | datetime | None = None,
) -> SearchFilters:
    """Normalize and validate filter inputs.

    - `path_prefix` accepts a string or a list/tuple of strings.
    - `extensions` accepts a list/tuple, or a comma-separated string for CLI use.
      Entries are lowercased and gain a leading dot if missing.
    - `since` accepts an ISO 8601 datetime string or a `datetime`. Naive
      datetimes are assumed to be UTC. Invalid input raises ``ValueError``.
    """
    if path_prefix is None or path_prefix == "":
        prefixes: tuple[str, ...] = ()
    elif isinstance(path_prefix, str):
        prefixes = (path_prefix,)
    else:
        prefixes = tuple(p for p in path_prefix if p)

    if extensions is None or extensions == "":
        exts: tuple[str, ...] = ()
    elif isinstance(extensions, str):
        exts = _split_extensions((extensions,))
    else:
        exts = _split_extensions(extensions)

    parsed_since: datetime | None = None
    if since is not None and since != "":
        if isinstance(since, datetime):
            parsed_since = since
        elif isinstance(since, str):
            try:
                parsed_since = datetime.fromisoformat(since)
            except ValueError as exc:
                raise ValueError(
                    f"Invalid `since` value {since!r}: expected ISO 8601 "
                    "datetime (e.g. 2026-01-01T00:00:00Z)"
                ) from exc
        else:
            raise ValueError(
                f"Invalid `since` value: expected ISO 8601 string or datetime, "
                f"got {type(since).__name__}"
            )
        if parsed_since.tzinfo is None:
            parsed_since = parsed_since.replace(tzinfo=UTC)

    return SearchFilters(
        path_prefix=prefixes,
        extensions=exts,
        since=parsed_since,
    )


def filters_to_chroma_where(filters: SearchFilters) -> dict | None:
    """Build a Chroma `where` clause from filters, or None if no push-down applies.

    Chroma metadata filtering supports equality, `$in`, `$gte`, `$lte`, `$and`,
    and `$or`, but no prefix-matching on string fields. So `extension` and
    `since` push down; `path_prefix` is applied post-fetch.
    """
    clauses: list[dict] = []

    if filters.extensions:
        if len(filters.extensions) == 1:
            clauses.append({"extension": filters.extensions[0]})
        else:
            clauses.append({"extension": {"$in": list(filters.extensions)}})

    if filters.since is not None:
        clauses.append({"source_mtime": {"$gte": filters.since.timestamp()}})

    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def apply_filters_to_hits(
    hits: list[dict[str, Any]],
    filters: SearchFilters,
) -> list[dict[str, Any]]:
    """Return hits that satisfy every supplied filter."""
    if filters.is_empty:
        return hits

    kept: list[dict[str, Any]] = []
    for hit in hits:
        path = str(hit.get("path", ""))
        ext = hit.get("extension")
        if not ext:
            ext = _Path(path).suffix.lower()
        mtime_raw = hit.get("source_mtime")
        mtime = float(mtime_raw) if mtime_raw is not None else None
        if filters.matches_record(path, str(ext), mtime):
            kept.append(hit)
    return kept


def _candidate_fetch_size(top_k: int, filters: SearchFilters) -> int:
    """Decide how many candidates to fetch when filters may discard some."""
    if filters.is_empty:
        return top_k
    return min(top_k * _FILTER_OVERSAMPLE, _MAX_OVERSAMPLE_FETCH)


def _semantic_fetch_size(top_k: int, filters: SearchFilters) -> int:
    """Fetch enough vector candidates for local lexical tie-breaking."""
    semantic_top_k = max(
        top_k,
        min(top_k * _SEMANTIC_OVERSAMPLE, _SEMANTIC_MAX_CANDIDATES),
    )
    return _candidate_fetch_size(semantic_top_k, filters)


def _normalize_rank_term(term: str) -> str:
    term = term.lower()
    return term[:-1] if len(term) > 3 and term.endswith("s") else term


def _rank_terms(text: str, *, remove_stopwords: bool = False) -> set[str]:
    terms = {
        _normalize_rank_term(term)
        for term in re.findall(r"[A-Za-z0-9_/-]+", text)
        if len(term) > 1
    }
    if remove_stopwords:
        terms -= _SEMANTIC_STOPWORDS
    return terms


def _semantic_lexical_boost(query: str, hit: dict[str, Any]) -> float:
    """Small deterministic boost for exact lexical anchors in semantic results."""
    query_terms = _rank_terms(query, remove_stopwords=True)
    if not query_terms:
        return 0.0

    title_terms = _rank_terms(str(hit.get("title", "")))
    path_terms = _rank_terms(str(hit.get("path", "")))
    content_terms = _rank_terms(str(hit.get("content", "")))

    boost = 0.0
    if title_terms == query_terms:
        boost += 0.20
    elif query_terms and query_terms.issubset(title_terms):
        boost += 0.08
    elif title_terms:
        boost += 0.04 * (len(query_terms & title_terms) / len(query_terms))

    if path_terms:
        boost += 0.04 * (len(query_terms & path_terms) / len(query_terms))

    if content_terms:
        content_overlap = len(query_terms & content_terms) / len(query_terms)
        if len(query_terms) == 1:
            boost += min(0.02, 0.02 * content_overlap)
        else:
            boost += min(0.18, 0.22 * content_overlap)

    return min(boost, 0.30)


class ChromaQueryCollection(Protocol):
    """Minimal Chroma collection surface used by semantic search."""

    def query(
        self,
        *,
        query_embeddings: list[list[float]],
        n_results: int,
        include: list[str],
        where: dict | None = ...,
    ) -> dict[str, list]: ...


class SemanticSearch:
    """Vector-based semantic search using ChromaDB."""

    # Class-level LRU cache keyed by (model_slug, query) to prevent cross-model collisions
    _embedding_cache: ClassVar[OrderedDict[tuple[str, str], list[float]]] = (
        OrderedDict()
    )
    _cache_hits: ClassVar[int] = 0
    _cache_misses: ClassVar[int] = 0
    _cache_maxsize: ClassVar[int] = 1000

    def __init__(
        self,
        collection: ChromaQueryCollection,
        backend: EmbeddingBackend | None = None,
    ):
        """Initialize semantic search.

        Args:
            collection: ChromaDB collection with indexed documents.
            backend: Embedding backend for encoding queries. Uses default if None.
        """
        self.collection = collection
        self.backend = backend or build_embedding_backend()
        self._model_slug = settings.model_slug

    def _get_query_embedding(self, query: str) -> list[float]:
        """Get embedding for query, using LRU cache keyed by (model_slug, query)."""
        cache_key = (self._model_slug, query)
        cached = self._embedding_cache.get(cache_key)
        if cached is not None:
            SemanticSearch._cache_hits += 1
            self._embedding_cache.move_to_end(cache_key)
            return list(cached)

        SemanticSearch._cache_misses += 1
        embedding = self.backend.encode_one(query).tolist()

        if len(self._embedding_cache) >= self._cache_maxsize:
            self._embedding_cache.popitem(last=False)

        self._embedding_cache[cache_key] = embedding
        return list(embedding)

    @classmethod
    def get_cache_stats(cls) -> dict:
        """Get cache statistics."""
        total = cls._cache_hits + cls._cache_misses
        hit_rate = cls._cache_hits / total if total > 0 else 0.0
        return {
            "cache_size": len(cls._embedding_cache),
            "cache_maxsize": cls._cache_maxsize,
            "cache_hits": cls._cache_hits,
            "cache_misses": cls._cache_misses,
            "cache_hit_rate": f"{hit_rate:.1%}",
        }

    def search(
        self,
        query: str,
        top_k: int = 10,
        filters: SearchFilters | None = None,
    ) -> list[dict]:
        """Search by semantic similarity, optionally scoped by filters."""
        if not query or not query.strip():
            return []
        top_k = _clamp_top_k(top_k)
        filters = filters or SearchFilters()

        query_embedding = self._get_query_embedding(query)
        n_results = _semantic_fetch_size(top_k, filters)
        where = filters_to_chroma_where(filters)

        query_kwargs: dict[str, Any] = {
            "query_embeddings": [query_embedding],
            "n_results": n_results,
            "include": ["documents", "metadatas", "distances"],
        }
        if where is not None:
            query_kwargs["where"] = where
        results = self.collection.query(**query_kwargs)

        built: list = []
        for i, doc_id in enumerate(results["ids"][0]):
            distance = results["distances"][0][i]
            similarity = 1 - distance
            metadata = results["metadatas"][0][i]
            built.append(
                hit_from_chroma(
                    doc_id,
                    metadata,
                    results["documents"][0][i],
                    similarity,
                )
            )

        hits = apply_filters_to_hits(hits_to_dicts(built), filters)
        ranked_hits: list[tuple[float, dict[str, Any]]] = []
        for hit in hits:
            boost = _semantic_lexical_boost(query, hit)
            if boost:
                hit["semantic_score"] = hit["score"]
                hit["lexical_boost"] = boost
            ranked_hits.append((float(hit.get("score", 0.0)) + boost, hit))
        ranked_hits.sort(key=lambda item: item[0], reverse=True)
        return [hit for _, hit in ranked_hits[:top_k]]


class KeywordSearch:
    """BM25-based keyword search for fast lexical matching."""

    def __init__(self, indexer: WikiIndexer):
        """Initialize keyword search.

        Args:
            indexer: WikiIndexer with loaded BM25 index and corpus metadata.
        """
        self.indexer = indexer

    def search(
        self,
        keyword: str,
        max_results: int = 20,
        filters: SearchFilters | None = None,
    ) -> list[dict]:
        """Search using BM25 for fast keyword matching, optionally filtered."""
        if not keyword or not keyword.strip():
            return []
        max_results = _clamp_top_k(max_results, default=20)
        filters = filters or SearchFilters()

        bm25 = self.indexer.bm25
        metadata_list = self.indexer.bm25_corpus

        if bm25 is None or not metadata_list:
            return []

        query_tokens = tokenize_keywords(keyword)

        # Over-fetch when filters are active so we can return `max_results`
        # in-scope hits after dropping out-of-scope ones.
        fetch_n = _candidate_fetch_size(max_results, filters)
        fetch_n = min(fetch_n, len(metadata_list))
        results, scores = bm25.retrieve(query_tokens, k=fetch_n)

        built = []
        for i, result in enumerate(results[0]):
            score = float(scores[0][i])
            if score <= 0:
                continue

            if isinstance(result, dict):
                doc_idx = result.get("id", -1)
                doc_content = result.get("text", "")
            else:
                doc_idx = int(result)
                doc_content = ""

            if doc_idx < 0 or doc_idx >= len(metadata_list):
                continue

            metadata = metadata_list[doc_idx]
            built.append(hit_from_bm25(metadata, doc_content, score))

        hits = apply_filters_to_hits(hits_to_dicts(built), filters)
        return hits[:max_results]


class HybridSearch:
    """Combined semantic + keyword search with RRF ranking and optional reranking."""

    # Lazy-loaded reranker (shared across instances)
    _reranker: ClassVar[CrossEncoder | None] = None

    def __init__(self, indexer: WikiIndexer, backend: EmbeddingBackend | None = None):
        """Initialize hybrid search.

        Args:
            indexer: WikiIndexer with ChromaDB collection and BM25 index.
            backend: Embedding backend for semantic search. Uses default if None.
        """
        self.semantic = SemanticSearch(indexer.collection, backend)
        self.keyword = KeywordSearch(indexer)

    @classmethod
    def _get_reranker(cls) -> CrossEncoder | None:
        if not settings.reranker_enabled:
            return None
        if cls._reranker is None:
            cls._reranker = CrossEncoder(settings.reranker_model)
        return cls._reranker

    def search(
        self,
        query: str,
        top_k: int = 10,
        semantic_weight: float | None = None,
        rerank: bool | None = None,
        filters: SearchFilters | None = None,
    ) -> list[dict]:
        """Hybrid search using RRF with optional cross-encoder reranking.

        Args:
            query: Search query
            top_k: Number of results to return
            semantic_weight: Weight for semantic vs keyword (0-1). If None, auto-detected.
            rerank: Override reranking setting (None uses RERANKER_ENABLED env var)
            filters: Optional filters; applied within both underlying searches.
        """
        if not query or not query.strip():
            return []
        top_k = _clamp_top_k(top_k)
        filters = filters or SearchFilters()

        query_type: str | None = None
        if semantic_weight is None:
            query_type, semantic_weight = classify_query(query)
            logger.debug(
                "Query classified as '%s', weight=%s", query_type, semantic_weight
            )

        use_rerank = rerank if rerank is not None else settings.reranker_enabled

        # Reranking benefits from a wider candidate pool.
        candidate_multiplier = 3 if use_rerank else 2
        n_candidates = top_k * candidate_multiplier

        semantic_results = self.semantic.search(
            query, top_k=n_candidates, filters=filters
        )
        keyword_results = self.keyword.search(
            query, max_results=n_candidates, filters=filters
        )

        rrf_scores: dict[str, float] = defaultdict(float)
        doc_data: dict[str, dict] = {}
        k = 60  # RRF constant

        # Dedup by chunk ID, not file path, so multiple chunks of one doc can co-rank.
        for rank, hit in enumerate(semantic_results):
            chunk_id = hit["id"]
            rrf_scores[chunk_id] += semantic_weight * (1 / (k + rank + 1))
            if chunk_id not in doc_data:
                doc_data[chunk_id] = hit

        for rank, hit in enumerate(keyword_results):
            chunk_id = hit["id"]
            rrf_scores[chunk_id] += (1 - semantic_weight) * (1 / (k + rank + 1))
            if chunk_id not in doc_data:
                doc_data[chunk_id] = hit

        ranked_ids = heapq.nlargest(
            top_k * candidate_multiplier, rrf_scores, key=rrf_scores.__getitem__
        )

        candidates = []
        for chunk_id in ranked_ids:
            result = doc_data[chunk_id].copy()
            result["rrf_score"] = rrf_scores[chunk_id]
            result["source"] = "hybrid"
            candidates.append(result)

        if use_rerank and candidates:
            reranker = self._get_reranker()
            if reranker is not None:
                pairs = [(query, c["content"]) for c in candidates]
                scores = reranker.predict(pairs)

                for i, c in enumerate(candidates):
                    c["rerank_score"] = float(scores[i])
                candidates.sort(key=lambda x: x["rerank_score"], reverse=True)

        return candidates[:top_k]


NeighborLookup = Callable[[str, int, int], list[dict[str, Any]]]


def _query_terms(query: str) -> list[str]:
    """Extract meaningful lowercase terms for hints and snippets."""
    return [
        term for term in re.findall(r"[A-Za-z0-9_/-]+", query.lower()) if len(term) > 1
    ]


def _lexical_match_hints(query: str, hit: dict[str, Any]) -> list[str]:
    """Return grounded lexical hints for a hit."""
    terms = _query_terms(query)
    if not terms:
        return []

    fields = {
        "title": str(hit.get("title", "")),
        "path": str(hit.get("path", "")),
        "breadcrumb": str(hit.get("breadcrumb", "")),
        "content": str(hit.get("content", "")),
    }
    hints: list[str] = []
    for label, value in fields.items():
        value_lower = value.lower()
        matched = sorted({term for term in terms if term in value_lower})
        if matched:
            hints.append(f"{label} matches: {', '.join(matched[:5])}")
    return hints


def add_match_hints(query: str, hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach grounded match hints to hits."""
    hinted: list[dict[str, Any]] = []
    for hit in hits:
        item = hit.copy()
        hints = _lexical_match_hints(query, item)
        if not hints and item.get("source") in {"semantic", "hybrid"}:
            score = item.get("rerank_score", item.get("rrf_score", item.get("score")))
            if isinstance(score, float):
                hints.append(f"{item.get('source')} retrieval score: {score:.3f}")
            else:
                hints.append(f"{item.get('source')} retrieval match")
        if hints:
            item["match_hints"] = hints
        hinted.append(item)
    return hinted


class SmartSearch:
    """BM25-first search orchestration with transparent fallback behavior."""

    def __init__(self, indexer: WikiIndexer, backend: EmbeddingBackend | None = None):
        self.keyword = KeywordSearch(indexer)
        self.hybrid = HybridSearch(indexer, backend)

    @staticmethod
    def _keyword_strength(
        query: str,
        hits: list[dict[str, Any]],
        top_k: int,
    ) -> tuple[bool, str]:
        if not hits:
            return False, "BM25 returned no positive-score results"

        best_score = float(hits[0].get("score", 0) or 0)
        distinct_docs = {hit.get("path") for hit in hits}
        requested = max(1, min(top_k, SMART_KEYWORD_STRENGTH_TOP_K))
        conceptual = is_conceptual_query(query)
        # Confidence for conceptual queries is the count of *strong* hits, not the
        # raw hit count: a common query word (e.g. "set" in "how do I set X")
        # matches many docs weakly and would otherwise look like a confident BM25
        # result, letting smart skip a fallback it should take.
        strong_hits = sum(
            1
            for hit in hits
            if float(hit.get("score", 0) or 0) >= BM25_STRONG_HIT_FRACTION * best_score
        )

        if best_score <= 0:
            return False, "BM25 best score was not positive"
        if best_score < BM25_WEAK_BEST_SCORE:
            return False, "BM25 best score was very low"
        runner_up = float(hits[1].get("score", 0) or 0) if len(hits) > 1 else 0.0
        if len(hits) > 1 and len(distinct_docs) == 1 and conceptual:
            return False, "BM25 results were duplicate-heavy for a conceptual query"
        if (
            conceptual
            and runner_up > 0
            and best_score >= BM25_DECISIVE_TOP_MARGIN * runner_up
        ):
            return True, "conceptual query had a decisive BM25 top hit"
        if conceptual and strong_hits < requested:
            return False, "conceptual query had too few strong BM25 hits"
        if conceptual and strong_hits < top_k:
            return False, "conceptual query lacks enough strong BM25 hits"
        if (
            conceptual
            and runner_up > 0
            and best_score < BM25_DOMINANCE_MARGIN * runner_up
        ):
            return False, "no dominant BM25 match for a conceptual query"

        return True, "BM25 returned strong exact-match results"

    def search(
        self,
        query: str,
        top_k: int = 10,
        filters: SearchFilters | None = None,
    ) -> SmartSearchResult:
        """Run BM25 first, then fall back to hybrid retrieval when needed."""
        filters = filters or SearchFilters()
        if not query or not query.strip():
            return SmartSearchResult(
                hits=[],
                route=SearchRoute(
                    strategy="keyword",
                    reason="empty query",
                    fallback_used=False,
                    filters=filters,
                ),
            )

        top_k = _clamp_top_k(top_k)
        keyword_hits = self.keyword.search(query, max_results=top_k, filters=filters)
        strong, reason = self._keyword_strength(query, keyword_hits, top_k)

        if strong:
            return SmartSearchResult(
                hits=add_match_hints(query, keyword_hits),
                route=SearchRoute(
                    strategy="keyword",
                    reason=reason,
                    fallback_used=False,
                    filters=filters,
                ),
            )

        hybrid_hits = self.hybrid.search(query, top_k=top_k, filters=filters)
        return SmartSearchResult(
            hits=add_match_hints(query, hybrid_hits),
            route=SearchRoute(
                strategy="hybrid",
                reason=reason,
                fallback_used=True,
                filters=filters,
            ),
        )
