"""Search implementations for wiki knowledge base."""

from __future__ import annotations

import logging
from collections import OrderedDict, defaultdict
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
    _embedding_cache: ClassVar[OrderedDict[tuple[str, str], tuple[float, ...]]] = (
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
        if cache_key in self._embedding_cache:
            SemanticSearch._cache_hits += 1
            self._embedding_cache.move_to_end(cache_key)
            return list(self._embedding_cache[cache_key])

        SemanticSearch._cache_misses += 1
        embedding = tuple(self.backend.encode_one(query).tolist())

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
            # ChromaDB returns cosine distance, convert to similarity
            distance = results["distances"][0][i]
            similarity = 1 - distance

            hits.append(
                {
                    "id": doc_id,
                    "path": results["metadatas"][0][i]["path"],
                    "title": results["metadatas"][0][i]["title"],
                    "folder": results["metadatas"][0][i]["folder"],
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

        if bm25 is None or metadata_list is None:
            return []
        if not metadata_list:
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
        """Lazy load reranker model."""
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

        # Auto-detect semantic weight based on query type if not provided
        query_type: str | None = None
        if semantic_weight is None:
            query_type, semantic_weight = self._classify_query(query)
            logger.debug(
                "Query classified as '%s', weight=%s", query_type, semantic_weight
            )

        # Determine if reranking should be used
        use_rerank = rerank if rerank is not None else settings.reranker_enabled

        # Fast path: when auto-detecting and rerank is off, route by query type
        if query_type == "keyword" and not use_rerank:
            return self.keyword.search(query, max_results=top_k)
        if query_type in {"question", "default"} and not use_rerank:
            return self.semantic.search(query, top_k=top_k)

        # Get more candidates if reranking
        candidate_multiplier = 3 if use_rerank else 2
        n_candidates = top_k * candidate_multiplier

        # Get results from both methods
        semantic_results = self.semantic.search(query, top_k=n_candidates)
        keyword_results = self.keyword.search(query, max_results=n_candidates)

        # Calculate RRF scores
        rrf_scores: dict[str, float] = defaultdict(float)
        doc_data: dict[str, dict] = {}
        k = 60  # RRF constant

        # Process semantic results (dedup by chunk ID, not file path)
        for rank, hit in enumerate(semantic_results):
            chunk_id = hit["id"]
            rrf_scores[chunk_id] += semantic_weight * (1 / (k + rank + 1))
            if chunk_id not in doc_data:
                doc_data[chunk_id] = hit

        # Process keyword results
        for rank, hit in enumerate(keyword_results):
            chunk_id = hit["id"]
            rrf_scores[chunk_id] += (1 - semantic_weight) * (1 / (k + rank + 1))
            if chunk_id not in doc_data:
                doc_data[chunk_id] = hit

        # Sort by RRF score
        ranked_ids = sorted(
            rrf_scores.keys(), key=lambda cid: rrf_scores[cid], reverse=True
        )

        # Build candidate results
        candidates = []
        for chunk_id in ranked_ids[: top_k * candidate_multiplier]:
            result = doc_data[chunk_id].copy()
            result["rrf_score"] = rrf_scores[chunk_id]
            result["source"] = "hybrid"
            candidates.append(result)

        # Optional reranking with cross-encoder
        if use_rerank and candidates:
            reranker = self._get_reranker()
            if reranker is not None:
                pairs = [(query, c["content"]) for c in candidates]
                scores = reranker.predict(pairs)

                for i, c in enumerate(candidates):
                    c["rerank_score"] = float(scores[i])
                candidates.sort(key=lambda x: x["rerank_score"], reverse=True)

        return candidates[:top_k]


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
            content = hit.get("content", "")
            if len(content) > 500:
                cut = content.rfind(" ", 0, 500)
                content = content[: cut if cut > 0 else 500] + "..."
            lines.append(f"\n**Preview:**\n{content}\n")

    return "\n".join(lines)
