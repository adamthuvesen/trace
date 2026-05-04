"""Search implementations for wiki knowledge base."""

from __future__ import annotations

import heapq
import logging
import re
from collections import OrderedDict, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

import bm25s
import Stemmer
from sentence_transformers import CrossEncoder

from trace_search.config import settings
from trace_search.embeddings import EmbeddingBackend, build_embedding_backend

if TYPE_CHECKING:
    from trace_search.indexer import WikiIndexer

logger = logging.getLogger(__name__)


def _clamp_top_k(top_k: int, default: int = 10, max_val: int = 100) -> int:
    """Clamp top_k to valid range [1, max_val]."""
    if top_k < 1:
        return default
    return min(top_k, max_val)


class SemanticSearch:
    """Vector-based semantic search using ChromaDB."""

    # Class-level LRU cache keyed by (model_slug, query) to prevent cross-model collisions
    _embedding_cache: ClassVar[OrderedDict[tuple[str, str], list[float]]] = (
        OrderedDict()
    )
    _cache_hits: ClassVar[int] = 0
    _cache_misses: ClassVar[int] = 0
    _cache_maxsize: ClassVar[int] = 1000

    def __init__(self, collection, backend: EmbeddingBackend | None = None):
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

    def search(self, query: str, top_k: int = 10) -> list[dict]:
        """Search by semantic similarity."""
        if not query or not query.strip():
            return []
        top_k = _clamp_top_k(top_k)

        query_embedding = self._get_query_embedding(query)

        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )

        hits = []
        for i, doc_id in enumerate(results["ids"][0]):
            # ChromaDB returns cosine distance; convert to similarity.
            distance = results["distances"][0][i]
            similarity = 1 - distance
            metadata = results["metadatas"][0][i]

            hits.append(
                {
                    "id": doc_id,
                    "path": metadata["path"],
                    "title": metadata["title"],
                    "folder": metadata["folder"],
                    "chunk_index": metadata.get("chunk_index"),
                    "chunk_count": metadata.get("chunk_count"),
                    "breadcrumb": metadata.get("breadcrumb"),
                    "content": results["documents"][0][i],
                    "score": similarity,
                    "source": "semantic",
                }
            )

        return hits


class KeywordSearch:
    """BM25-based keyword search for fast lexical matching."""

    def __init__(self, indexer: WikiIndexer):
        """Initialize keyword search.

        Args:
            indexer: WikiIndexer with loaded BM25 index and corpus metadata.
        """
        self.indexer = indexer
        self._stemmer = Stemmer.Stemmer("english")

    def search(self, keyword: str, max_results: int = 20) -> list[dict]:
        """Search using BM25 for fast keyword matching."""
        if not keyword or not keyword.strip():
            return []
        max_results = _clamp_top_k(max_results, default=20)

        bm25 = self.indexer.bm25
        metadata_list = self.indexer.bm25_corpus

        if bm25 is None or not metadata_list:
            return []

        query_tokens = bm25s.tokenize(
            [keyword],
            stopwords="en",
            stemmer=self._stemmer,
        )

        # When corpus is loaded, results are dicts with 'id' (index) and 'text' (content)
        results, scores = bm25.retrieve(query_tokens, k=max_results)

        hits = []
        for i, result in enumerate(results[0]):
            score = float(scores[0][i])
            if score <= 0:
                continue

            # Handle both dict format (with corpus) and int format (without corpus loaded)
            if isinstance(result, dict):
                doc_idx = result.get("id", -1)
                doc_content = result.get("text", "")
            else:
                doc_idx = int(result)
                doc_content = ""

            if doc_idx < 0 or doc_idx >= len(metadata_list):
                continue

            metadata = metadata_list[doc_idx]

            hits.append(
                {
                    "id": f"{metadata['path']}::{metadata['chunk_index']}",
                    "path": metadata["path"],
                    "title": metadata["title"],
                    "folder": metadata["folder"],
                    "chunk_index": metadata.get("chunk_index"),
                    "chunk_count": metadata.get("chunk_count"),
                    "breadcrumb": metadata.get("breadcrumb"),
                    "content": doc_content,
                    "score": score,
                    "source": "keyword",
                }
            )

        return hits


class HybridSearch:
    """Combined semantic + keyword search with RRF ranking and optional reranking."""

    # Lazy-loaded reranker (shared across instances)
    _reranker: ClassVar[CrossEncoder | None] = None

    # Query type weights (semantic_weight)
    WEIGHT_KEYWORD = 0.4  # Short keyword queries favor BM25
    WEIGHT_QUESTION = 0.7  # Question queries favor semantic

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

    def _classify_query(self, query: str) -> tuple[str, float]:
        """Classify query type and return optimal semantic weight.

        Returns:
            Tuple of (query_type, semantic_weight)
        """
        query_lower = query.lower().strip()
        words = query_lower.split()

        if not words:
            return ("default", self.WEIGHT_QUESTION)

        # Questions benefit from semantic understanding
        question_starters = {"what", "how", "where", "when", "why", "which", "who"}
        if words[0] in question_starters:
            return ("question", self.WEIGHT_QUESTION)

        # Short queries favor BM25 exact matching
        if len(words) <= 2:
            return ("keyword", self.WEIGHT_KEYWORD)

        return ("default", self.WEIGHT_QUESTION)

    def search(
        self,
        query: str,
        top_k: int = 10,
        semantic_weight: float | None = None,
        rerank: bool | None = None,
    ) -> list[dict]:
        """Hybrid search using RRF with optional cross-encoder reranking.

        Args:
            query: Search query
            top_k: Number of results to return
            semantic_weight: Weight for semantic vs keyword (0-1). If None, auto-detected.
            rerank: Override reranking setting (None uses RERANKER_ENABLED env var)
        """
        if not query or not query.strip():
            return []
        top_k = _clamp_top_k(top_k)

        query_type: str | None = None
        if semantic_weight is None:
            query_type, semantic_weight = self._classify_query(query)
            logger.debug(
                "Query classified as '%s', weight=%s", query_type, semantic_weight
            )

        use_rerank = rerank if rerank is not None else settings.reranker_enabled

        # Reranking benefits from a wider candidate pool.
        candidate_multiplier = 3 if use_rerank else 2
        n_candidates = top_k * candidate_multiplier

        semantic_results = self.semantic.search(query, top_k=n_candidates)
        keyword_results = self.keyword.search(query, max_results=n_candidates)

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


@dataclass(frozen=True)
class SearchRoute:
    """Routing metadata for smart search."""

    strategy: str
    reason: str
    fallback_used: bool


@dataclass(frozen=True)
class SmartSearchResult:
    """Smart search hits plus transparent routing metadata."""

    hits: list[dict[str, Any]]
    route: SearchRoute


NeighborLookup = Callable[[str, int, int], list[dict[str, Any]]]


def _query_terms(query: str) -> list[str]:
    """Extract meaningful lowercase terms for hints and snippets."""
    return [
        term for term in re.findall(r"[A-Za-z0-9_/-]+", query.lower()) if len(term) > 1
    ]


def _is_conceptual_query(query: str) -> bool:
    words = query.lower().strip().split()
    if not words:
        return False
    if words[0] in {"what", "how", "where", "when", "why", "which", "who"}:
        return True
    return len(words) >= 5


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
        requested = max(1, min(top_k, 3))

        if best_score <= 0:
            return False, "BM25 best score was not positive"
        if len(hits) < requested and _is_conceptual_query(query):
            return False, "conceptual query had too few BM25 hits"
        if best_score < 0.05:
            return False, "BM25 best score was very low"
        if len(hits) > 1 and len(distinct_docs) == 1 and _is_conceptual_query(query):
            return False, "BM25 results were duplicate-heavy for a conceptual query"
        if _is_conceptual_query(query) and len(hits) < top_k:
            return False, "conceptual query may benefit from hybrid retrieval"

        return True, "BM25 returned strong exact-match results"

    def search(self, query: str, top_k: int = 10) -> SmartSearchResult:
        """Run BM25 first, then fall back to hybrid retrieval when needed."""
        if not query or not query.strip():
            return SmartSearchResult(
                hits=[],
                route=SearchRoute(
                    strategy="keyword",
                    reason="empty query",
                    fallback_used=False,
                ),
            )

        top_k = _clamp_top_k(top_k)
        keyword_hits = self.keyword.search(query, max_results=top_k)
        strong, reason = self._keyword_strength(query, keyword_hits, top_k)

        if strong:
            return SmartSearchResult(
                hits=add_match_hints(query, keyword_hits),
                route=SearchRoute(
                    strategy="keyword",
                    reason=reason,
                    fallback_used=False,
                ),
            )

        hybrid_hits = self.hybrid.search(query, top_k=top_k)
        return SmartSearchResult(
            hits=add_match_hints(query, hybrid_hits),
            route=SearchRoute(
                strategy="hybrid",
                reason=reason,
                fallback_used=True,
            ),
        )


def _trim_at_boundary(text: str, limit: int) -> str:
    """Trim text at a readable boundary."""
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    cut = compact.rfind(" ", 0, limit)
    return compact[: cut if cut > 0 else limit].rstrip() + "..."


def _best_quote(content: str, query: str, limit: int = 360) -> str | None:
    """Extract a concise quote-ready snippet."""
    compact = re.sub(r"\s+", " ", content).strip()
    if not compact:
        return None

    terms = _query_terms(query)
    lowered = compact.lower()
    positions = [lowered.find(term) for term in terms if lowered.find(term) >= 0]
    if positions:
        pos = min(positions)
        start = max(0, pos - 120)
        end = min(len(compact), pos + limit - 120)
        snippet = compact[start:end]
        if start > 0:
            snippet = "..." + snippet
        if end < len(compact):
            snippet += "..."
        return _trim_at_boundary(snippet, limit)

    return _trim_at_boundary(compact, limit)


def _normalization_key(text: str) -> str:
    """Normalize text for near-duplicate suppression."""
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()[:220]


def _score_for_sort(hit: dict[str, Any]) -> float:
    score = hit.get("rerank_score", hit.get("rrf_score", hit.get("score", 0)))
    return float(score or 0)


def _format_followups(hits: list[dict[str, Any]], limit: int = 3) -> list[str]:
    seen: set[tuple[str | None, str]] = set()
    followups: list[str] = []
    for hit in hits:
        path = hit.get("path")
        if not path:
            continue
        collection = hit.get("collection")
        key = (collection, str(path))
        if key in seen:
            continue
        seen.add(key)
        if collection:
            followups.append(
                f'- `get_document(path="{path}", collection="{collection}")`'
            )
        else:
            followups.append(f'- `get_document(path="{path}")`')
        if len(followups) >= limit:
            break
    return followups


def format_context_packets(
    hits: list[dict[str, Any]],
    *,
    query: str,
    route: SearchRoute | None = None,
    max_documents: int = 5,
    max_snippets_per_document: int = 2,
) -> str:
    """Render agent-native context grouped by document."""
    if not hits:
        if route is None:
            return "No results found."
        return (
            "No results found.\n\n"
            f"**Strategy:** {route.strategy}\n"
            f"**Reason:** {route.reason}"
        )

    sorted_hits = sorted(hits, key=_score_for_sort, reverse=True)
    lines = [f"Found {len(hits)} results"]

    if route is not None:
        fallback = "yes" if route.fallback_used else "no"
        lines.extend(
            [
                "",
                "## Strategy",
                f"- **Selected:** {route.strategy}",
                f"- **Fallback used:** {fallback}",
                f"- **Reason:** {route.reason}",
            ]
        )

    grouped: dict[tuple[str | None, str], list[dict[str, Any]]] = defaultdict(list)
    for hit in sorted_hits:
        grouped[(hit.get("collection"), str(hit.get("path", "")))].append(hit)

    document_groups = sorted(
        grouped.values(),
        key=lambda group: max(_score_for_sort(hit) for hit in group),
        reverse=True,
    )[:max_documents]

    lines.extend(["", "## Context"])
    global_seen: set[tuple[str | None, str]] = set()
    for index, group in enumerate(document_groups, 1):
        first = group[0]
        path = str(first.get("path", ""))
        title = first.get("title") or path or "Untitled"
        collection = first.get("collection")
        source = first.get("source", "unknown")
        folder = first.get("folder", "")
        lines.append("")
        lines.append(f"### {index}. {title}")
        lines.append(f"- **Path:** `{path}`")
        if collection:
            lines.append(f"- **Collection:** {collection}")
        if folder:
            lines.append(f"- **Folder:** {folder}")
        lines.append(f"- **Source:** {source}")

        per_doc_seen: set[str] = set()
        snippets_added = 0
        for hit in group:
            quote = _best_quote(str(hit.get("content", "")), query)
            if not quote:
                continue
            normalized = _normalization_key(quote)
            global_key = (collection, normalized)
            if normalized in per_doc_seen:
                continue
            if global_key in global_seen and len(document_groups) > 1:
                continue
            per_doc_seen.add(normalized)
            global_seen.add(global_key)

            breadcrumb = hit.get("breadcrumb") or title
            lines.append("")
            lines.append(f"**Snippet {snippets_added + 1}:** {breadcrumb}")
            hints = hit.get("match_hints") or []
            if hints:
                lines.append(f"- **Match evidence:** {'; '.join(hints[:3])}")
            matched_terms = [
                term for term in _query_terms(query) if term in quote.lower()
            ]
            if matched_terms:
                terms = ", ".join(f"`{term}`" for term in sorted(set(matched_terms)))
                lines.append(f"- **Matched terms:** {terms}")
            lines.append(f"- **Best quote:** {quote}")

            neighbor = hit.get("neighbor_content")
            if neighbor:
                lines.append(
                    f"- **Nearby context:** {_trim_at_boundary(str(neighbor), 220)}"
                )

            snippets_added += 1
            if snippets_added >= max_snippets_per_document:
                break

    followups = _format_followups(sorted_hits)
    if followups:
        lines.extend(["", "## Suggested Follow-ups"])
        lines.extend(followups)

    return "\n".join(lines)


def format_smart_search(result: SmartSearchResult, query: str) -> str:
    """Format smart search results with route metadata and context packets."""
    return format_context_packets(result.hits, query=query, route=result.route)


def format_results(hits: list[dict[str, Any]], include_content: bool = True) -> str:
    """Format search results for display."""
    if not hits:
        return "No results found."

    lines = [f"Found {len(hits)} results:\n"]

    for i, hit in enumerate(hits, 1):
        score_str = (
            f"{hit.get('score', 0):.3f}"
            if isinstance(hit.get("score"), float)
            else str(hit.get("score", ""))
        )
        source = hit.get("source", "unknown")

        lines.append(f"---\n### {i}. {hit['title']}")
        lines.append(f"**Path:** `{hit['path']}`")
        if "collection" in hit:
            lines.append(f"**Collection:** {hit['collection']}")
        lines.append(f"**Folder:** {hit['folder']}")

        if source == "keyword":
            lines.append(f"**BM25 Score:** {score_str}")
        elif source == "semantic":
            lines.append(f"**Similarity:** {score_str}")
        elif source == "hybrid":
            rrf = hit.get("rrf_score", 0)
            rerank = hit.get("rerank_score")
            if rerank is not None:
                lines.append(f"**Rerank Score:** {rerank:.3f} (RRF: {rrf:.4f})")
            else:
                lines.append(f"**RRF Score:** {rrf:.4f}")

        if include_content:
            content = _trim_at_boundary(hit.get("content", ""), 500)
            lines.append(f"\n**Preview:**\n{content}\n")

    return "\n".join(lines)
