"""Search implementations for local knowledge bases."""

from __future__ import annotations

import heapq
import logging
import math
import re
import threading
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import TYPE_CHECKING, ClassVar

import numpy as np
from numpy.typing import NDArray

from trace_search.indexing.bm25_tokenize import tokenize_keywords
from trace_search.indexing.index_store import ChunkMetadata, IndexSnapshot
from trace_search.indexing.index_metadata import metadata_query_compatible
from trace_search.indexing.embeddings import EmbeddingBackend
from trace_search.retrieval.hit_builders import typed_chunk_hit
from trace_search.retrieval.formatting import (  # noqa: F401 - package re-exports
    _query_terms,
    format_results,
    format_search_context,
)
from trace_search.retrieval.query_profile import (
    BM25_DOMINANCE_MARGIN,
    LEXICAL_STOPWORDS,
    is_keywordish_query,
)
from trace_search.retrieval.search_types import (
    AdaptiveSearchResult as AdaptiveSearchResult,
    SearchResult,
    SearchRoute as SearchRoute,
    SearchFilters as SearchFilters,
    SearchHit,
    SearchResponse,
    DocumentRef,
    parse_filters as parse_filters,
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
# Pages whose frontmatter says a newer page replaced them stay findable but
# rank below their replacement, in every mode.
_REPLACED_STATUSES = frozenset({"superseded", "deprecated"})
_REPLACED_DEMOTION = 0.7
# A query "names" a page when every query term is in its title or one alias and
# covers at least this share of that name's terms.
_NAME_COVERAGE = 0.6
_NAME_MATCH_GAIN = 3.0
_ADAPTIVE_MIN_FALLBACK_SEMANTIC_SCORE = 0.40
# Vector similarity alone ranks near-duplicates arbitrarily; the lexical boost
# re-ranks a wider candidate pool so exact title/term anchors can surface.
_SEMANTIC_CANDIDATE_POOL = 50


def _clamp_top_k(top_k: int, default: int = 10, max_val: int = 100) -> int:
    """Clamp top_k to valid range [1, max_val]."""
    if top_k < 1:
        return default
    return min(top_k, max_val)


def _normalize_rank_term(term: str) -> str:
    term = term.lower()
    return term[:-1] if len(term) > 3 and term.endswith("s") else term


def _extract_rank_terms(text: str, remove_stopwords: bool = False) -> frozenset[str]:
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
    return frozenset(terms)


# Titles, paths, breadcrumbs, and aliases repeat across the hundreds of chunk
# hits one query scores; tokenizing them once matters. Chunk texts are cached
# per snapshot instead (`IndexSnapshot.row_terms`), so this stays small.
@lru_cache(maxsize=16384)
def _rank_terms(text: str, *, remove_stopwords: bool = False) -> frozenset[str]:
    return _extract_rank_terms(text, remove_stopwords)


def _semantic_lexical_boost(
    query: str, hit: SearchHit | SearchResult, content_terms: frozenset[str]
) -> float:
    """Small deterministic boost for exact lexical anchors in semantic results."""
    hit = SearchHit.from_dict(hit) if isinstance(hit, dict) else hit
    query_terms = _rank_terms(query, remove_stopwords=True)
    if not query_terms:
        return 0.0

    path_terms = _rank_terms(hit.path)

    # A page's aliases are names just like its title.
    boost = max(
        (
            0.20
            if name == query_terms
            else 0.08
            if query_terms <= name
            else 0.04 * (len(query_terms & name) / len(query_terms))
            for name in _page_names(hit)
        ),
        default=0.0,
    )

    if path_terms:
        boost += 0.04 * (len(query_terms & path_terms) / len(query_terms))

    if content_terms:
        content_overlap = len(query_terms & content_terms) / len(query_terms)
        if len(query_terms) == 1:
            boost += min(0.02, 0.02 * content_overlap)
        else:
            boost += min(0.18, 0.22 * content_overlap)

    return min(boost, 0.30)


def _metadata_overlap(query_terms: frozenset[str], hit: SearchHit) -> float:
    if not query_terms:
        return 0.0
    metadata_terms = (
        _rank_terms(hit.metadata["title"])
        | _rank_terms(hit.path)
        | _rank_terms(hit.metadata["breadcrumb"])
        | _rank_terms(hit.metadata["folder"])
        | _rank_terms(hit.metadata.get("aliases", ""))
    )
    if not metadata_terms:
        return 0.0
    return len(query_terms & metadata_terms) / len(query_terms)


def _page_names(hit: SearchHit) -> list[frozenset[str]]:
    """Term sets of a page's title and each of its aliases."""
    names = [hit.metadata["title"], *hit.metadata.get("aliases", "").split(";")]
    return [
        terms for name in names if (terms := _rank_terms(name, remove_stopwords=True))
    ]


def _query_names_page(query_terms: frozenset[str], hit: SearchHit) -> bool:
    """Whether the query is essentially one of the page's names.

    A navigational query ("internal tools overview", an alias like "hobby
    builds") should land on the page it names even when longer pages repeat
    those words more often. Partial overlap is handled by the metadata boost.
    """
    if not query_terms:
        return False
    return any(
        query_terms <= name and len(query_terms) / len(name) >= _NAME_COVERAGE
        for name in _page_names(hit)
    )


def _status_factor(hit: SearchHit) -> float:
    """Demotion factor for pages marked as replaced by a newer page."""
    return (
        _REPLACED_DEMOTION if hit.metadata.get("status") in _REPLACED_STATUSES else 1.0
    )


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
    best_hit: SearchHit
    best_score: float
    metadata_overlap: float
    names_query: bool = False
    chunk_scores: list[float] = field(default_factory=list)

    def add_hit(
        self,
        hit: SearchHit,
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

        if self.names_query:
            score += best * _NAME_MATCH_GAIN
        elif _is_navigational_hub(self.best_hit.path):
            score *= _HUB_DEMOTION
        return score * _status_factor(self.best_hit)

    def to_hit(self, file_score: float) -> SearchHit:
        return replace(
            self.best_hit,
            evidence=replace(
                self.best_hit.evidence,
                score=file_score,
                bm25_chunk_score=self.best_score,
                bm25_file_score=file_score,
                bm25_file_support=len(self.chunk_scores),
                bm25_metadata_overlap=self.metadata_overlap,
            ),
        )


def _aggregate_keyword_hits(
    query: str,
    hits: list[SearchHit],
    max_results: int,
    *,
    corpus_size: int,
    require_anchor_for_weak_hits: bool = True,
) -> list[SearchHit]:
    """Promote files with multiple good chunks while returning one hit per file."""
    if not hits:
        return []

    query_terms = _rank_terms(query, remove_stopwords=True)
    grouped: dict[str, _KeywordHitGroup] = {}
    for hit in hits:
        path = hit.path
        if not path:
            continue
        score = hit.evidence.score
        overlap = _metadata_overlap(query_terms, hit)
        group = grouped.get(path)
        if group is None:
            group = _KeywordHitGroup(
                best_hit=hit,
                best_score=score,
                metadata_overlap=overlap,
                names_query=_query_names_page(query_terms, hit),
            )
            grouped[path] = group
        group.add_hit(hit, score=score, metadata_overlap=overlap)

    weak_score = _weak_file_score(corpus_size)
    ranked: list[tuple[float, int, SearchHit]] = []
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


class SemanticSearch:
    """Exact cosine search over the snapshot's normalized embedding matrix."""

    # Backend ownership prevents injected runtimes from sharing incompatible vectors.
    _embedding_cache: ClassVar[
        OrderedDict[tuple[int, str], tuple[EmbeddingBackend, NDArray[np.float32]]]
    ] = OrderedDict()
    _cache_hits: ClassVar[int] = 0
    _cache_misses: ClassVar[int] = 0
    _cache_maxsize: ClassVar[int] = 1000
    # Searches on different collections share this cache from worker threads;
    # an eviction between get and move_to_end would raise KeyError.
    _cache_lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self, indexer: WikiIndexer):
        """Initialize semantic search over an indexer's current snapshot."""
        self.indexer = indexer

    def _get_query_embedding(self, query: str) -> NDArray[np.float32]:
        """Get the normalized query embedding, cached by backend ownership and query."""
        backend = self.indexer.backend
        cache_key = (id(backend), query)
        with self._cache_lock:
            cached = self._embedding_cache.get(cache_key)
            if cached is not None:
                SemanticSearch._cache_hits += 1
                self._embedding_cache.move_to_end(cache_key)
                return cached[1]
            SemanticSearch._cache_misses += 1

        vector = np.asarray(backend.encode_one(query), dtype=np.float32)
        if vector.ndim != 1 or not np.isfinite(vector).all():
            raise ValueError("Embedding backend returned an invalid query vector")
        norm = float(np.linalg.norm(vector))
        embedding = vector / norm if norm else vector

        with self._cache_lock:
            if len(self._embedding_cache) >= self._cache_maxsize:
                self._embedding_cache.popitem(last=False)
            self._embedding_cache[cache_key] = (backend, embedding)
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
        snapshot: IndexSnapshot | None = None,
    ) -> list[SearchResult]:
        return [hit.to_dict() for hit in self.rank(query, top_k, filters, snapshot)]

    def rank(
        self,
        query: str,
        top_k: int = 10,
        filters: SearchFilters | None = None,
        snapshot: IndexSnapshot | None = None,
    ) -> list[SearchHit]:
        """Search by semantic similarity, optionally scoped by filters."""
        if not query or not query.strip():
            return []
        top_k = _clamp_top_k(top_k)
        filters = filters or SearchFilters()
        if snapshot is None:
            snapshot = self.indexer.snapshot()
        if not len(snapshot):
            return []

        if snapshot.metadata is not None and not metadata_query_compatible(
            snapshot.metadata, self.indexer.config, self.indexer.backend
        ):
            raise ValueError(
                "Index embedding backend is incompatible. Run `reindex` before semantic search."
            )
        query_vector = self._get_query_embedding(query)
        if query_vector.shape != (snapshot.embeddings.shape[1],):
            raise ValueError(
                "Query embedding dimensions differ from index. Run `reindex`."
            )
        scores = snapshot.embeddings @ query_vector
        mask = _filter_mask(snapshot, filters)
        pool = min(max(top_k, _SEMANTIC_CANDIDATE_POOL), len(snapshot))
        if mask is not None:
            scores = np.where(mask, scores, -np.inf)
            pool = min(pool, int(mask.sum()))
        if pool <= 0:
            return []
        rows = np.argpartition(-scores, pool - 1)[:pool]
        rows = rows[np.argsort(-scores[rows], kind="stable")]

        ranked_hits: list[tuple[float, SearchHit]] = []
        for row in rows:
            hit = typed_chunk_hit(
                snapshot.chunks[row],
                snapshot.texts[row],
                float(scores[row]),
                "semantic",
                snapshot.generation,
            )
            content_terms = snapshot.row_terms(int(row), _extract_rank_terms)
            boost = _semantic_lexical_boost(query, hit, content_terms)
            if boost:
                hit = replace(
                    hit,
                    evidence=replace(
                        hit.evidence,
                        semantic_score=hit.evidence.score,
                        lexical_boost=boost,
                    ),
                )
            ranked_hits.append(
                ((hit.evidence.score + boost) * _status_factor(hit), hit)
            )
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
        snapshot: IndexSnapshot | None = None,
    ) -> list[SearchResult]:
        return [
            hit.to_dict() for hit in self.rank(keyword, max_results, filters, snapshot)
        ]

    def rank(
        self,
        keyword: str,
        max_results: int = 20,
        filters: SearchFilters | None = None,
        snapshot: IndexSnapshot | None = None,
    ) -> list[SearchHit]:
        """Search using BM25 for fast keyword matching, optionally filtered."""
        if not keyword or not keyword.strip():
            return []
        max_results = _clamp_top_k(max_results, default=20)
        filters = filters or SearchFilters()
        if snapshot is None:
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

        hits: list[SearchHit] = []
        for i, result in enumerate(results[0]):
            score = float(scores[0][i])
            if score <= 0:
                continue
            row = int(result)
            if row < 0 or row >= len(snapshot):
                continue
            hits.append(
                typed_chunk_hit(
                    snapshot.chunks[row],
                    snapshot.texts[row],
                    score,
                    "keyword",
                    snapshot.generation,
                )
            )

        return _aggregate_keyword_hits(
            keyword,
            hits,
            max_results,
            corpus_size=len(snapshot),
            require_anchor_for_weak_hits=filters.is_empty,
        )


_RRF_K = 60
# BM25 leads the fusion. 0.4 beat 0.5 on a private wiki (adaptive MRR +0.013) and
# a team KB (hybrid +0.028) and tied on the paraphrase-heavy smoke fixture.
_SEMANTIC_FUSION_WEIGHT = 0.4


def _fuse_by_document(
    weighted_lists: list[tuple[float, list[SearchResult]]], limit: int
) -> list[SearchResult]:
    return [
        hit.to_dict()
        for hit in _fuse_typed(
            [
                (weight, [SearchHit.from_dict(hit) for hit in hits])
                for weight, hits in weighted_lists
            ],
            limit,
        )
    ]


def _fuse_typed(
    weighted_lists: list[tuple[float, list[SearchHit]]], limit: int
) -> list[SearchHit]:
    """Reciprocal-rank fusion at document level.

    Each list contributes its best-ranked chunk per document, so a page that
    both retrievers find combines its evidence instead of splitting it across
    chunk ids. The representative hit comes from the first list that has the
    document.
    """
    fused: dict[DocumentRef, float] = defaultdict(float)
    representative: dict[DocumentRef, SearchHit] = {}
    for weight, hits in weighted_lists:
        seen: set[DocumentRef] = set()
        for hit in hits:
            path = hit.ref.document
            if path in seen:
                continue
            fused[path] += weight / (_RRF_K + len(seen) + 1)
            seen.add(path)
            representative.setdefault(path, hit)
    ranked = heapq.nlargest(limit, fused, key=fused.__getitem__)
    return [
        replace(
            representative[path],
            evidence=replace(representative[path].evidence, rrf_score=fused[path]),
            source="hybrid",
        )
        for path in ranked
    ]


class HybridSearch:
    """Semantic + keyword search fused by reciprocal rank per document."""

    def __init__(self, indexer: WikiIndexer):
        """Initialize hybrid search over an indexer's current snapshot."""
        self.semantic = SemanticSearch(indexer)
        self.keyword = KeywordSearch(indexer)

    def search(
        self,
        query: str,
        top_k: int = 10,
        semantic_weight: float = _SEMANTIC_FUSION_WEIGHT,
        filters: SearchFilters | None = None,
        snapshot: IndexSnapshot | None = None,
    ) -> list[SearchResult]:
        return [
            hit.to_dict()
            for hit in self.rank(query, top_k, semantic_weight, filters, snapshot)
        ]

    def rank(
        self,
        query: str,
        top_k: int = 10,
        semantic_weight: float = _SEMANTIC_FUSION_WEIGHT,
        filters: SearchFilters | None = None,
        snapshot: IndexSnapshot | None = None,
    ) -> list[SearchHit]:
        """Hybrid search: BM25 files and semantic chunks fused per document.

        Args:
            query: Search query
            top_k: Number of results to return
            semantic_weight: Weight of the semantic ranking in the fusion (0-1).
            filters: Optional filters; applied within both underlying searches.
        """
        if not query or not query.strip():
            return []
        top_k = _clamp_top_k(top_k)
        filters = filters or SearchFilters()

        n_candidates = top_k * 2
        # Both rankings read one generation, so a reindex published mid-query
        # cannot fuse chunks from two different index states.
        snapshot = snapshot if snapshot is not None else self.keyword.indexer.snapshot()

        # Semantic hits are chunks and several can share a file; fetch deeper
        # so fusion still sees enough distinct documents.
        semantic_results = self.semantic.rank(
            query, top_k=n_candidates * 2, filters=filters, snapshot=snapshot
        )
        keyword_results = self.keyword.rank(
            query, max_results=n_candidates, filters=filters, snapshot=snapshot
        )
        candidates = _fuse_typed(
            [
                (1 - semantic_weight, keyword_results),
                (semantic_weight, semantic_results),
            ],
            n_candidates,
        )

        return candidates[:top_k]


def add_match_hints(query: str, hits: list[SearchResult]) -> list[SearchResult]:
    """Compatibility wrapper around typed match evidence."""
    return [
        hit.to_dict()
        for hit in _typed_match_hints(query, [SearchHit.from_dict(hit) for hit in hits])
    ]


def _typed_match_hints(query: str, hits: list[SearchHit]) -> tuple[SearchHit, ...]:
    terms = _query_terms(query)
    output: list[SearchHit] = []
    for hit in hits:
        hints: list[str] = []
        for label, value in (
            ("title", hit.metadata["title"]),
            ("path", hit.path),
            ("breadcrumb", hit.metadata["breadcrumb"]),
            ("content", hit.content),
        ):
            matched = sorted({term for term in terms if term in value.lower()})
            if matched:
                hints.append(f"{label} matches: {', '.join(matched[:5])}")
        if not hints and hit.source in {"semantic", "hybrid"}:
            score = (
                hit.evidence.rrf_score
                if hit.evidence.rrf_score is not None
                else hit.evidence.score
            )
            hints.append(f"{hit.source} retrieval score: {score:.3f}")
        output.append(replace(hit, match_hints=tuple(hints)))
    return tuple(output)


class AdaptiveSearch:
    """BM25-first adaptive search with transparent fallback behavior."""

    def __init__(self, indexer: WikiIndexer):
        self.keyword = KeywordSearch(indexer)
        self.hybrid = HybridSearch(indexer)

    @staticmethod
    def _fallback_confident(hits: list[SearchHit]) -> bool:
        if not hits:
            return False
        best_score = hits[0].evidence.score
        return best_score >= _ADAPTIVE_MIN_FALLBACK_SEMANTIC_SCORE

    @staticmethod
    def _keyword_strength(hits: list[SearchHit]) -> tuple[bool, str]:
        """Trust BM25 alone only when its top document clearly leads.

        A near-tie at the top means the lexical evidence does not single out a
        page (common words in a broad question, or several pages sharing the
        vocabulary), so fusing in semantic ranking is the better bet.
        """
        if not hits:
            return False, "BM25 returned no positive-score results"
        if len(hits) == 1:
            # One lexical match is as likely a coincidence (a paraphrase that
            # shares one word with some page) as a precise hit; fusion keeps it
            # on top when semantic ranking agrees.
            return False, "BM25 matched only one document"
        best = hits[0].evidence.score
        runner_up = hits[1].evidence.score
        margin = best / runner_up if runner_up > 0 else float("inf")
        if margin >= BM25_DOMINANCE_MARGIN:
            return True, f"BM25 top hit leads the runner-up {margin:.2f}x"
        return False, f"no dominant BM25 hit (top leads runner-up {margin:.2f}x)"

    def response(
        self,
        query: str,
        top_k: int = 10,
        filters: SearchFilters | None = None,
        snapshot: IndexSnapshot | None = None,
    ) -> SearchResponse:
        """Run BM25 first, then fall back to hybrid retrieval when needed."""
        filters = filters or SearchFilters()
        if not query or not query.strip():
            return SearchResponse(
                hits=(),
                route=SearchRoute(
                    strategy="keyword",
                    reason="empty query",
                    fallback_used=False,
                    filters=filters,
                ),
            )

        top_k = _clamp_top_k(top_k)
        snapshot = snapshot if snapshot is not None else self.keyword.indexer.snapshot()
        # The confidence gate compares the top hit with the runner-up, so fetch
        # at least two even when the caller asked for one.
        keyword_hits = self.keyword.rank(
            query, max_results=max(top_k, 2), filters=filters, snapshot=snapshot
        )
        if not keyword_hits and is_keywordish_query(query):
            return SearchResponse(
                hits=(),
                route=SearchRoute(
                    strategy="keyword",
                    reason="keyword query had no meaningful BM25 hits",
                    fallback_used=False,
                    filters=filters,
                ),
            )

        strong, reason = self._keyword_strength(keyword_hits)

        if strong:
            return SearchResponse(
                hits=_typed_match_hints(query, keyword_hits[:top_k]),
                route=SearchRoute(
                    strategy="keyword",
                    reason=reason,
                    fallback_used=False,
                    filters=filters,
                ),
            )

        hybrid_hits = self.hybrid.rank(
            query, top_k=top_k, filters=filters, snapshot=snapshot
        )
        if (
            not keyword_hits
            and filters.is_empty
            and not self._fallback_confident(hybrid_hits)
        ):
            return SearchResponse(
                hits=(),
                route=SearchRoute(
                    strategy="hybrid",
                    reason="hybrid fallback confidence was too low",
                    fallback_used=True,
                    filters=filters,
                ),
            )
        return SearchResponse(
            hits=_typed_match_hints(query, hybrid_hits),
            route=SearchRoute(
                strategy="hybrid",
                reason=reason,
                fallback_used=True,
                filters=filters,
            ),
        )

    def search(
        self,
        query: str,
        top_k: int = 10,
        filters: SearchFilters | None = None,
        snapshot: IndexSnapshot | None = None,
    ) -> AdaptiveSearchResult:
        response = self.response(query, top_k, filters, snapshot)
        assert response.route is not None
        return AdaptiveSearchResult(response.legacy_hits(), response.route)
