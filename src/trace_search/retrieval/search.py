"""Search implementations for local knowledge bases."""

from __future__ import annotations

import heapq
import logging
import math
import re
import threading
from collections import OrderedDict, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar, Protocol

import numpy as np
from numpy.typing import NDArray

from trace_search.retrieval.bm25_tokenize import tokenize_keywords
from trace_search.config import settings
from trace_search.indexing.index_store import ChunkMetadata, IndexSnapshot
from trace_search.retrieval.hit_builders import (
    hit_from_bm25,
    hit_from_vector,
    hits_to_dicts,
)
from trace_search.retrieval.models import SearchHit
from trace_search.retrieval.formatting import (  # noqa: F401 - package re-exports
    format_results,
    format_search_context,
)
from trace_search.retrieval.query_profile import (
    ADAPTIVE_KEYWORD_STRENGTH_TOP_K,
    BM25_DOMINANCE_MARGIN,
    BM25_DECISIVE_TOP_MARGIN,
    BM25_STRONG_HIT_FRACTION,
    BM25_WEAK_BEST_SCORE,
    LEXICAL_STOPWORDS,
    classify_query,
    is_conceptual_query,
    is_keywordish_query,
)
from trace_search.retrieval.search_types import (
    AdaptiveSearchResult,
    SearchResult,
    SearchRoute,
)

if TYPE_CHECKING:
    from trace_search.indexing.wiki_indexer import WikiIndexer

logger = logging.getLogger(__name__)

_MAX_CHUNK_FETCH = 500
# File-level BM25 rolls chunk hits up into files, so the chunk pool must be deep
# enough to cover enough distinct files. Long files (navigational hubs, verbose
# essays) each occupy many chunk slots, so a shallow pool starves precise pages
# whose single best chunk sits just outside it. Oversample generously by file.
_BM25_FILE_OVERSAMPLE = 25
_BM25_MIN_FILE_FETCH = 200
_BM25_WEAK_FILE_SCORE_LOG_FACTOR = 0.72
_BM25_WEAK_METADATA_OVERLAP = 0.20

# File-score aggregation weights (see _KeywordHitGroup.file_score).
# Support rewards a file with several chunks nearly as strong as its best, scored
# relative to that best so raw chunk count cannot inflate a long or link-dense
# file. Metadata boost lifts pages whose title/path/breadcrumb name the query
# terms — a precise topical match — over verbose pages that merely mention them;
# the gain is large because overlap is diluted by long natural-language queries.
# Navigational hubs (index/log link-dumps) are demoted, not filtered, so they can
# still answer catalog questions but do not outrank the content pages they list.
_SUPPORT_TOP_M = 3
_SUPPORT_GAIN = 0.3
_METADATA_BOOST_GAIN = 4.0
_METADATA_BOOST_CAP = 1.5
_HUB_DEMOTION = 0.4
_NAVIGATIONAL_HUB_BASENAMES = frozenset({"index.md", "log.md", "changelog.md"})
_ADAPTIVE_MIN_FALLBACK_SEMANTIC_SCORE = 0.40
# Vector similarity alone ranks near-duplicates arbitrarily; the lexical boost
# re-ranks a wider candidate pool so exact title/term anchors can surface.
_SEMANTIC_CANDIDATE_POOL = 50


def _clamp_top_k(top_k: int, default: int = 10, max_val: int = 100) -> int:
    """Clamp top_k to valid range [1, max_val]."""
    if top_k < 1:
        return default
    return min(top_k, max_val)


@dataclass(frozen=True)
class SearchFilters:
    """Optional scope filters applied across all search modes.

    Filters are evaluated before ranking as a row mask over the index snapshot:
    BM25 receives it as a weight mask and vector search skips masked rows. The
    empty `SearchFilters()` is a no-op.
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


def _parse_path_prefixes(
    path_prefix: str | list[str] | tuple[str, ...] | None,
) -> tuple[str, ...]:
    if path_prefix is None or path_prefix == "":
        return ()
    if isinstance(path_prefix, str):
        return (path_prefix,)
    return tuple(prefix for prefix in path_prefix if prefix)


def _parse_extensions(
    extensions: str | list[str] | tuple[str, ...] | None,
) -> tuple[str, ...]:
    if extensions is None or extensions == "":
        return ()
    if isinstance(extensions, str):
        return _split_extensions((extensions,))
    return _split_extensions(extensions)


def _parse_since(since: str | datetime | None) -> datetime | None:
    if since is None or since == "":
        return None

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
        return parsed_since.replace(tzinfo=UTC)
    return parsed_since


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
    return SearchFilters(
        path_prefix=_parse_path_prefixes(path_prefix),
        extensions=_parse_extensions(extensions),
        since=_parse_since(since),
    )


def _normalize_rank_term(term: str) -> str:
    term = term.lower()
    return term[:-1] if len(term) > 3 and term.endswith("s") else term


def _rank_terms(text: str, *, remove_stopwords: bool = False) -> set[str]:
    terms: set[str] = set()
    for term in re.findall(r"[A-Za-z0-9_/-]+", text):
        if len(term) <= 1:
            continue
        terms.add(_normalize_rank_term(term))
        for part in re.split(r"[/_-]+", term):
            if len(part) > 1:
                terms.add(_normalize_rank_term(part))
    if remove_stopwords:
        terms -= LEXICAL_STOPWORDS
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


def _metadata_overlap(query_terms: set[str], hit: dict[str, Any]) -> float:
    if not query_terms:
        return 0.0
    metadata_terms = (
        _rank_terms(str(hit.get("title", "")))
        | _rank_terms(str(hit.get("path", "")))
        | _rank_terms(str(hit.get("breadcrumb", "")))
        | _rank_terms(str(hit.get("folder", "")))
    )
    if not metadata_terms:
        return 0.0
    return len(query_terms & metadata_terms) / len(query_terms)


def _keyword_fetch_size(max_results: int) -> int:
    return min(
        max(max_results * _BM25_FILE_OVERSAMPLE, _BM25_MIN_FILE_FETCH),
        _MAX_CHUNK_FETCH,
    )


def _filter_mask(
    snapshot: IndexSnapshot, filters: SearchFilters
) -> NDArray[np.bool_] | None:
    """Rows that satisfy the filters, or None when no filter is active."""
    if filters.is_empty:
        return None

    def keep(chunk: ChunkMetadata) -> bool:
        return filters.matches_record(
            chunk["path"], chunk["extension"], chunk["source_mtime"]
        )

    return snapshot.row_mask(filters, keep)


def _weak_file_score(corpus_size: int) -> float:
    """Scale weak-hit abstention to the BM25 score range of the corpus."""
    return max(1.0, _BM25_WEAK_FILE_SCORE_LOG_FACTOR * math.log(max(corpus_size, 2)))


def _is_navigational_hub(path: str) -> bool:
    """Whether a path is a navigational hub (index/log link-dump), not content."""
    return path.rsplit("/", 1)[-1].lower() in _NAVIGATIONAL_HUB_BASENAMES


@dataclass
class _KeywordHitGroup:
    best_hit: dict[str, Any]
    best_score: float
    metadata_overlap: float
    chunk_scores: list[float] = field(default_factory=list)

    def add_hit(
        self,
        hit: dict[str, Any],
        *,
        score: float,
        metadata_overlap: float,
    ) -> None:
        self.chunk_scores.append(score)
        self.metadata_overlap = max(self.metadata_overlap, metadata_overlap)
        if score > self.best_score:
            self.best_hit = hit
            self.best_score = score

    def file_score(self) -> float:
        best = self.best_score
        if best <= 0:
            return best

        # Reward genuine multi-section coverage: the top-M secondary chunks scored
        # as a fraction of this file's own best, saturating so raw chunk count
        # cannot inflate a long or link-dense file.
        secondary = sorted(self.chunk_scores, reverse=True)[1 : 1 + _SUPPORT_TOP_M]
        support_ratio = sum(s / best for s in secondary)
        support_boost = _SUPPORT_GAIN * best * (support_ratio / (1.0 + support_ratio))

        metadata_boost = best * min(
            _METADATA_BOOST_CAP, _METADATA_BOOST_GAIN * self.metadata_overlap
        )
        score = best + support_boost + metadata_boost

        if _is_navigational_hub(str(self.best_hit.get("path", ""))):
            score *= _HUB_DEMOTION
        return score

    def to_hit(self, file_score: float) -> dict[str, Any]:
        hit = dict(self.best_hit)
        hit["bm25_chunk_score"] = self.best_score
        hit["bm25_file_score"] = file_score
        hit["bm25_file_support"] = len(self.chunk_scores)
        hit["bm25_metadata_overlap"] = self.metadata_overlap
        hit["score"] = file_score
        return hit


def _aggregate_keyword_hits(
    query: str,
    hits: list[dict[str, Any]],
    max_results: int,
    *,
    corpus_size: int,
    require_anchor_for_weak_hits: bool = True,
) -> list[dict[str, Any]]:
    """Promote files with multiple good chunks while returning one hit per file."""
    if not hits:
        return []

    query_terms = _rank_terms(query, remove_stopwords=True)
    grouped: dict[str, _KeywordHitGroup] = {}
    for hit in hits:
        path = str(hit.get("path", ""))
        if not path:
            continue
        score = float(hit.get("score", 0.0) or 0.0)
        overlap = _metadata_overlap(query_terms, hit)
        group = grouped.get(path)
        if group is None:
            group = _KeywordHitGroup(
                best_hit=hit,
                best_score=score,
                metadata_overlap=overlap,
            )
            grouped[path] = group
        group.add_hit(hit, score=score, metadata_overlap=overlap)

    weak_score = _weak_file_score(corpus_size)
    ranked: list[tuple[float, int, dict[str, Any]]] = []
    for order, group in enumerate(grouped.values()):
        file_score = group.file_score()

        if (
            require_anchor_for_weak_hits
            and file_score < weak_score
            and group.metadata_overlap < _BM25_WEAK_METADATA_OVERLAP
        ):
            continue

        ranked.append((file_score, -order, group.to_hit(file_score)))

    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [hit for _, _, hit in ranked[:max_results]]


class Reranker(Protocol):
    """The small part of the cross-encoder API used by hybrid search."""

    def predict(self, pairs: list[tuple[str, str]]) -> Sequence[float]: ...


class SemanticSearch:
    """Exact cosine search over the snapshot's normalized embedding matrix."""

    # Class-level LRU cache keyed by (model_slug, query) to prevent cross-model collisions
    _embedding_cache: ClassVar[OrderedDict[tuple[str, str], NDArray[np.float32]]] = (
        OrderedDict()
    )
    _cache_hits: ClassVar[int] = 0
    _cache_misses: ClassVar[int] = 0
    _cache_maxsize: ClassVar[int] = 1000
    # Searches on different collections share this cache from worker threads;
    # an eviction between get and move_to_end would raise KeyError.
    _cache_lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self, indexer: WikiIndexer):
        """Initialize semantic search over an indexer's current snapshot."""
        self.indexer = indexer
        self._model_slug = settings.model_slug

    def _get_query_embedding(self, query: str) -> NDArray[np.float32]:
        """Get the normalized query embedding, cached by (model_slug, query)."""
        cache_key = (self._model_slug, query)
        with self._cache_lock:
            cached = self._embedding_cache.get(cache_key)
            if cached is not None:
                SemanticSearch._cache_hits += 1
                self._embedding_cache.move_to_end(cache_key)
                return cached
            SemanticSearch._cache_misses += 1

        vector = np.asarray(self.indexer.backend.encode_one(query), dtype=np.float32)
        norm = float(np.linalg.norm(vector))
        embedding = vector / norm if norm else vector

        with self._cache_lock:
            if len(self._embedding_cache) >= self._cache_maxsize:
                self._embedding_cache.popitem(last=False)
            self._embedding_cache[cache_key] = embedding
        return embedding

    @classmethod
    def get_cache_stats(cls) -> dict[str, int | str]:
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
    ) -> list[SearchResult]:
        """Search by semantic similarity, optionally scoped by filters."""
        if not query or not query.strip():
            return []
        top_k = _clamp_top_k(top_k)
        filters = filters or SearchFilters()
        snapshot = self.indexer.snapshot()
        if not len(snapshot):
            return []

        scores = snapshot.embeddings @ self._get_query_embedding(query)
        mask = _filter_mask(snapshot, filters)
        pool = min(max(top_k, _SEMANTIC_CANDIDATE_POOL), len(snapshot))
        if mask is not None:
            scores = np.where(mask, scores, -np.inf)
            pool = min(pool, int(mask.sum()))
        if pool <= 0:
            return []
        rows = np.argpartition(-scores, pool - 1)[:pool]
        rows = rows[np.argsort(-scores[rows], kind="stable")]

        hits = hits_to_dicts(
            [
                hit_from_vector(
                    snapshot.chunk_ids[row],
                    snapshot.chunks[row],
                    snapshot.texts[row],
                    float(scores[row]),
                )
                for row in rows
            ]
        )
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
        """Initialize keyword search over an indexer's current snapshot."""
        self.indexer = indexer

    def search(
        self,
        keyword: str,
        max_results: int = 20,
        filters: SearchFilters | None = None,
    ) -> list[SearchResult]:
        """Search using BM25 for fast keyword matching, optionally filtered."""
        if not keyword or not keyword.strip():
            return []
        max_results = _clamp_top_k(max_results, default=20)
        filters = filters or SearchFilters()
        snapshot = self.indexer.snapshot()
        if snapshot.bm25 is None or not len(snapshot):
            return []

        mask = _filter_mask(snapshot, filters)
        if mask is not None and not mask.any():
            return []

        # Fetch a wider chunk pool so sibling chunks can vote for a file-level
        # result before truncation. The mask filters before ranking.
        fetch_n = min(_keyword_fetch_size(max_results), len(snapshot))
        results, scores = snapshot.bm25.retrieve(
            tokenize_keywords(keyword),
            k=fetch_n,
            show_progress=False,
            weight_mask=mask.astype(np.float32) if mask is not None else None,
        )

        built: list[SearchHit] = []
        for i, result in enumerate(results[0]):
            score = float(scores[0][i])
            if score <= 0:
                continue
            row = int(result)
            if row < 0 or row >= len(snapshot):
                continue
            built.append(
                hit_from_bm25(snapshot.chunks[row], snapshot.texts[row], score)
            )

        return _aggregate_keyword_hits(
            keyword,
            hits_to_dicts(built),
            max_results,
            corpus_size=len(snapshot),
            require_anchor_for_weak_hits=filters.is_empty,
        )


class HybridSearch:
    """Combined semantic + keyword search with RRF ranking and optional reranking."""

    # Lazy-loaded reranker (shared across instances)
    _reranker: ClassVar[Reranker | None] = None

    def __init__(self, indexer: WikiIndexer):
        """Initialize hybrid search over an indexer's current snapshot."""
        self.semantic = SemanticSearch(indexer)
        self.keyword = KeywordSearch(indexer)

    @classmethod
    def _get_reranker(cls) -> Reranker | None:
        if not settings.reranker_enabled:
            return None
        if cls._reranker is None:
            from sentence_transformers import CrossEncoder

            cls._reranker = CrossEncoder(settings.reranker_model)
        return cls._reranker

    def search(
        self,
        query: str,
        top_k: int = 10,
        semantic_weight: float | None = None,
        rerank: bool | None = None,
        filters: SearchFilters | None = None,
    ) -> list[SearchResult]:
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
        doc_data: dict[str, SearchResult] = {}
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

        candidates: list[SearchResult] = []
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


class AdaptiveSearch:
    """BM25-first adaptive search with transparent fallback behavior."""

    def __init__(self, indexer: WikiIndexer):
        self.keyword = KeywordSearch(indexer)
        self.hybrid = HybridSearch(indexer)

    @staticmethod
    def _fallback_confident(hits: list[dict[str, Any]]) -> bool:
        if not hits:
            return False
        best_score = float(hits[0].get("score", 0) or 0)
        return best_score >= _ADAPTIVE_MIN_FALLBACK_SEMANTIC_SCORE

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
        requested = max(1, min(top_k, ADAPTIVE_KEYWORD_STRENGTH_TOP_K))
        conceptual = is_conceptual_query(query)
        # Confidence for conceptual queries is the count of *strong* hits, not the
        # raw hit count: a common query word (e.g. "set" in "how do I set X")
        # matches many docs weakly and would otherwise look like a confident BM25
        # result, letting adaptive search skip a fallback it should take.
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
        metadata_overlap = float(hits[0].get("bm25_metadata_overlap", 0) or 0)
        if conceptual and metadata_overlap > 0:
            return True, "conceptual query had an anchored BM25 file hit"
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
    ) -> AdaptiveSearchResult:
        """Run BM25 first, then fall back to hybrid retrieval when needed."""
        filters = filters or SearchFilters()
        if not query or not query.strip():
            return AdaptiveSearchResult(
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
        if not keyword_hits and is_keywordish_query(query):
            return AdaptiveSearchResult(
                hits=[],
                route=SearchRoute(
                    strategy="keyword",
                    reason="keyword query had no meaningful BM25 hits",
                    fallback_used=False,
                    filters=filters,
                ),
            )

        strong, reason = self._keyword_strength(query, keyword_hits, top_k)

        if strong:
            return AdaptiveSearchResult(
                hits=add_match_hints(query, keyword_hits),
                route=SearchRoute(
                    strategy="keyword",
                    reason=reason,
                    fallback_used=False,
                    filters=filters,
                ),
            )

        hybrid_hits = self.hybrid.search(query, top_k=top_k, filters=filters)
        if (
            not keyword_hits
            and filters.is_empty
            and not self._fallback_confident(hybrid_hits)
        ):
            return AdaptiveSearchResult(
                hits=[],
                route=SearchRoute(
                    strategy="hybrid",
                    reason="hybrid fallback confidence was too low",
                    fallback_used=True,
                    filters=filters,
                ),
            )
        return AdaptiveSearchResult(
            hits=add_match_hints(query, hybrid_hits),
            route=SearchRoute(
                strategy="hybrid",
                reason=reason,
                fallback_used=True,
                filters=filters,
            ),
        )
