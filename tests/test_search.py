"""Tests for search module."""

from types import SimpleNamespace
from typing import get_type_hints
from unittest.mock import MagicMock

import numpy as np

from trace_search.config import settings
from trace_search.indexing.index_store import IndexSnapshot
from trace_search.retrieval.query_profile import is_keywordish_query
from trace_search.retrieval.search import (
    _BM25_MIN_FILE_FETCH,
    HybridSearch,
    KeywordSearch,
    SemanticSearch,
    _clamp_top_k,
    _fuse_by_document,
    _keyword_fetch_size,
    _extract_rank_terms,
    _semantic_lexical_boost,
)
from trace_search.retrieval.search_types import SearchRoute


class TestKeywordishQuery:
    def test_identifier_query_is_keywordish(self):
        assert is_keywordish_query("HTTP 429 Retry-After burst limit")

    def test_dense_noun_phrase_is_keywordish(self):
        assert is_keywordish_query(
            "term frequency saturation document length normalization"
        )

    def test_natural_question_is_not_keywordish(self):
        assert not is_keywordish_query("how does the growth model relate to funnels")

    def test_route_type_hints_resolve_at_runtime(self):
        assert "filters" in get_type_hints(SearchRoute)


class TestDocumentFusion:
    def test_page_found_by_both_retrievers_outranks_single_retriever_tops(self):
        # Semantic returns chunks (two from kw-top.md); keyword returns files.
        # both.md is second in each list and should win once fused per document.
        keyword = [
            {"id": "kw-top.md::0", "path": "kw-top.md"},
            {"id": "both.md::0", "path": "both.md"},
        ]
        semantic = [
            {"id": "sem-top.md::3", "path": "sem-top.md"},
            {"id": "sem-top.md::1", "path": "sem-top.md"},
            {"id": "both.md::2", "path": "both.md"},
        ]

        fused = _fuse_by_document([(0.5, keyword), (0.5, semantic)], limit=3)

        assert [hit["path"] for hit in fused] == ["both.md", "kw-top.md", "sem-top.md"]
        assert fused[0]["id"] == "both.md::0"  # keyword's chunk represents it
        assert all(hit["source"] == "hybrid" for hit in fused)


class TestEmptyCorpusSearch:
    def test_empty_corpus_returns_empty_list(self):
        indexer = SimpleNamespace(snapshot=IndexSnapshot.empty)

        assert KeywordSearch(indexer).search("anything") == []
        assert SemanticSearch(indexer).search("anything") == []


class TestKeywordSearchAggregation:
    """Fixed per-chunk BM25 scores isolate the file-level aggregation math."""

    class FakeBM25:
        def __init__(self, scores):
            self.scores = scores
            self.fetch_size = None

        def retrieve(self, _query_tokens, k, **_kwargs):
            self.fetch_size = k
            return [list(range(len(self.scores)))], [self.scores]

    @staticmethod
    def _indexer(bm25, chunks: list[dict]) -> SimpleNamespace:
        snapshot = IndexSnapshot(
            generation=None,
            metadata=None,
            chunk_ids=[f"{c['path']}::{c['chunk_index']}" for c in chunks],
            texts=[c["title"] for c in chunks],
            chunks=chunks,
            embeddings=np.zeros((len(chunks), 3), dtype=np.float32),
            bm25=bm25,
        )
        return SimpleNamespace(snapshot=lambda: snapshot)

    @staticmethod
    def _metadata(path: str, title: str, chunk_index: int) -> dict:
        return {
            "path": path,
            "title": title,
            "folder": "",
            "chunk_index": chunk_index,
            "chunk_count": 3,
            "breadcrumb": title,
            "extension": ".md",
            "source_mtime": 0.0,
        }

    @classmethod
    def _large_corpus_with(cls, first: dict) -> list[dict]:
        return [
            first,
            *[
                cls._metadata(f"filler/{index}.md", f"Filler {index}", 0)
                for index in range(4000)
            ],
        ]

    def test_keyword_search_aggregates_chunks_by_file_before_truncating(self):
        bm25 = TestKeywordSearchAggregation.FakeBM25([10.0, 9.8, 9.6])
        indexer = TestKeywordSearchAggregation._indexer(
            bm25,
            [
                TestKeywordSearchAggregation._metadata("wrong.md", "Wrong", 0),
                TestKeywordSearchAggregation._metadata("right.md", "Alpha", 0),
                TestKeywordSearchAggregation._metadata("right.md", "Alpha", 1),
            ],
        )

        hits = KeywordSearch(indexer).search("alpha", max_results=1)

        assert [hit["path"] for hit in hits] == ["right.md"]
        assert hits[0]["bm25_file_support"] == 2
        assert bm25.fetch_size == 3

    def test_keyword_fetch_size_oversamples_files(self):
        # File-level aggregation needs a deep chunk pool to cover enough distinct
        # files, even for a small result count.
        assert _keyword_fetch_size(1) >= _BM25_MIN_FILE_FETCH

    def test_navigational_hub_demoted_below_content_page(self):
        # index.md and a content page tie on best chunk score; the content page
        # should win because the hub is navigational, not an answer.
        bm25 = TestKeywordSearchAggregation.FakeBM25([6.0, 6.0])
        indexer = TestKeywordSearchAggregation._indexer(
            bm25,
            [
                TestKeywordSearchAggregation._metadata(
                    "notes/index.md", "Alpha index", 0
                ),
                TestKeywordSearchAggregation._metadata("notes/alpha.md", "Alpha", 0),
            ],
        )

        hits = KeywordSearch(indexer).search("alpha", max_results=2)
        assert [hit["path"] for hit in hits] == ["notes/alpha.md", "notes/index.md"]

    def test_support_boost_not_inflated_by_raw_chunk_count(self):
        # A file with one clearly stronger chunk beats a file with many weak
        # chunks. Neither has a metadata anchor, so this isolates support: the old
        # count-weighted support (capped at +2.0) let the 20-chunk file win, the
        # reshaped scale-free support does not.
        strong = TestKeywordSearchAggregation._metadata("strong.md", "Strong", 0)
        weak_chunks = [
            TestKeywordSearchAggregation._metadata("weak.md", "Weak", i)
            for i in range(20)
        ]

        bm25 = TestKeywordSearchAggregation.FakeBM25([7.5] + [6.0] * 20)
        indexer = TestKeywordSearchAggregation._indexer(
            bm25,
            [strong, *weak_chunks],
        )

        hits = KeywordSearch(indexer).search("zeta", max_results=2)
        assert hits[0]["path"] == "strong.md"
        assert hits[0]["score"] > hits[1]["score"]

    def test_keyword_search_drops_weak_hits_without_metadata_anchor(self):
        bm25 = TestKeywordSearchAggregation.FakeBM25([5.0])
        indexer = TestKeywordSearchAggregation._indexer(
            bm25,
            TestKeywordSearchAggregation._large_corpus_with(
                TestKeywordSearchAggregation._metadata("unrelated.md", "Unrelated", 0)
            ),
        )

        hits = KeywordSearch(indexer).search(
            "kubernetes pod security policy",
            max_results=5,
        )

        assert hits == []

    def test_keyword_search_keeps_weak_hits_with_strong_metadata_anchor(self):
        bm25 = TestKeywordSearchAggregation.FakeBM25([5.0])
        indexer = TestKeywordSearchAggregation._indexer(
            bm25,
            TestKeywordSearchAggregation._large_corpus_with(
                TestKeywordSearchAggregation._metadata(
                    "ops/kubernetes-pod-policy.md",
                    "Kubernetes pod policy",
                    0,
                )
            ),
        )

        hits = KeywordSearch(indexer).search(
            "kubernetes pod security policy",
            max_results=5,
        )

        assert [hit["path"] for hit in hits] == ["ops/kubernetes-pod-policy.md"]

    def test_keyword_search_drops_weak_hits_with_only_tiny_metadata_overlap(self):
        bm25 = TestKeywordSearchAggregation.FakeBM25([5.5])
        indexer = TestKeywordSearchAggregation._indexer(
            bm25,
            TestKeywordSearchAggregation._large_corpus_with(
                TestKeywordSearchAggregation._metadata(
                    "archive/unrelated.md",
                    "Unrelated note",
                    0,
                )
            ),
        )

        hits = KeywordSearch(indexer).search(
            "kubernetes pod security policy",
            max_results=5,
        )

        assert hits == []


class TestBM25Parameters:
    def test_bm25_params_in_settings(self):
        assert settings.bm25_k1 == 1.2
        assert settings.bm25_b == 0.5


class TestHybridSearchFusion:
    def test_short_query_uses_semantic_and_keyword_results(self):
        from unittest.mock import MagicMock

        hybrid = HybridSearch.__new__(HybridSearch)
        hybrid.semantic = MagicMock()
        hybrid.keyword = MagicMock()
        hybrid.semantic.search.return_value = [
            {
                "id": "semantic.md::0",
                "path": "semantic.md",
                "title": "Semantic",
                "folder": "",
                "content": "semantic content",
                "score": 0.9,
                "source": "semantic",
            }
        ]
        hybrid.keyword.search.return_value = [
            {
                "id": "keyword.md::0",
                "path": "keyword.md",
                "title": "Keyword",
                "folder": "",
                "content": "keyword content",
                "score": 2.0,
                "source": "keyword",
            }
        ]

        results = hybrid.search("RRF", top_k=2)

        hybrid.semantic.search.assert_called_once()
        hybrid.keyword.search.assert_called_once()
        assert {hit["path"] for hit in results} == {"semantic.md", "keyword.md"}
        assert all(hit["source"] == "hybrid" for hit in results)


class TestFormatResults:
    def test_format_results_empty_list(self):
        from trace_search.retrieval.search import format_results

        result = format_results([])
        assert result == "No results found."

    def test_format_results_minimal_hit(self):
        from trace_search.retrieval.search import format_results

        hits = [
            {"title": "Test Doc", "path": "test.md", "folder": "", "content": "text"}
        ]
        result = format_results(hits)
        assert "Test Doc" in result
        assert "test.md" in result

    def test_format_results_with_score(self):
        from trace_search.retrieval.search import format_results

        hits = [
            {
                "title": "Test",
                "path": "t.md",
                "folder": "Docs",
                "content": "content here",
                "score": 0.95,
                "source": "semantic",
            }
        ]
        result = format_results(hits)
        assert "0.95" in result
        assert "Similarity" in result

    def test_format_results_hybrid_with_rrf(self):
        from trace_search.retrieval.search import format_results

        hits = [
            {
                "title": "Test",
                "path": "t.md",
                "folder": "Docs",
                "content": "content",
                "score": 0.85,
                "source": "hybrid",
                "rrf_score": 0.0123,
            }
        ]
        result = format_results(hits)
        assert "RRF Score" in result
        assert "0.0123" in result

    def test_format_results_truncates_long_content(self):
        from trace_search.retrieval.search import format_results

        long_content = "x" * 600
        hits = [{"title": "T", "path": "t.md", "folder": "", "content": long_content}]
        result = format_results(hits)
        assert "..." in result
        assert long_content not in result

    def test_format_results_without_content(self):
        from trace_search.retrieval.search import format_results

        hits = [{"title": "T", "path": "t.md", "folder": "", "content": "secret"}]
        result = format_results(hits, include_content=False)
        assert "secret" not in result


class TestSemanticSearchCacheStats:
    def test_cache_stats_structure(self):
        from trace_search.retrieval.search import SemanticSearch

        stats = SemanticSearch.get_cache_stats()
        assert "cache_size" in stats
        assert "cache_maxsize" in stats
        assert "cache_hits" in stats
        assert "cache_misses" in stats
        assert "cache_hit_rate" in stats

    def test_cache_stats_types(self):
        from trace_search.retrieval.search import SemanticSearch

        stats = SemanticSearch.get_cache_stats()
        assert isinstance(stats["cache_size"], int)
        assert isinstance(stats["cache_maxsize"], int)
        assert isinstance(stats["cache_hits"], int)
        assert isinstance(stats["cache_misses"], int)
        assert isinstance(stats["cache_hit_rate"], str)


class TestSemanticLexicalBoost:
    def test_exact_title_gets_larger_boost_than_partial_title(self):
        query = "What are embeddings?"
        exact = {
            "title": "Embeddings",
            "path": "glossary/embeddings.md",
            "content": "Embeddings turn text into vectors.",
        }
        partial = {
            "title": "Embedding backend",
            "path": "config/embedding-backend.md",
            "content": "EMBEDDING_BACKEND config chooses onnx or torch.",
        }

        assert _semantic_lexical_boost(
            query, exact, _extract_rank_terms(exact["content"])
        ) > _semantic_lexical_boost(
            query, partial, _extract_rank_terms(partial["content"])
        )

    def test_content_overlap_boosts_header_queries(self):
        query = "HTTP 429 Retry-After burst limit"
        rate_limit = {
            "title": "Rate limits",
            "path": "api/rate-limits.md",
            "content": "HTTP 429 Retry-After burst sustained request limit.",
        }
        retryable = {
            "title": "Retryable errors",
            "path": "errors/retryable-errors.md",
            "content": "Retry HTTP 408, 429, and 503 with backoff.",
        }

        assert _semantic_lexical_boost(
            query, rate_limit, _extract_rank_terms(rate_limit["content"])
        ) > _semantic_lexical_boost(
            query, retryable, _extract_rank_terms(retryable["content"])
        )


class TestFormatResultsPreviewTruncation:
    def test_preview_ends_on_word_boundary(self):
        """Content over 500 chars should be cut at the last space before 500."""
        from trace_search.retrieval.search import format_results

        words = ["word"] * 200
        content = " ".join(words)
        assert len(content) > 500

        hit = {
            "title": "Test",
            "path": "test.md",
            "folder": "",
            "content": content,
            "score": 1.0,
            "source": "keyword",
        }
        result = format_results([hit])
        preview_start = result.index("**Preview:**\n") + len("**Preview:**\n")
        preview = result[preview_start:].strip().rstrip("\n")
        assert preview.endswith("...")
        body = preview[:-3]
        assert not body.endswith(" "), (
            "Should not end with a trailing space before ellipsis"
        )
        assert " " not in body[-5:] or body[-1] != " "

    def test_content_under_500_not_truncated(self):
        from trace_search.retrieval.search import format_results

        content = "short content"
        hit = {
            "title": "Test",
            "path": "test.md",
            "folder": "",
            "content": content,
            "score": 1.0,
            "source": "keyword",
        }
        result = format_results([hit])
        assert "short content" in result
        assert "..." not in result


class TestSemanticSearchCacheIsolation:
    @staticmethod
    def _search(model_slug: str, vector: list[float]) -> SemanticSearch:
        backend = MagicMock()
        backend.encode_one.return_value = np.asarray(vector, dtype=np.float32)
        search = SemanticSearch(SimpleNamespace(backend=backend))
        search._model_slug = model_slug
        return search

    def test_cache_key_includes_model_slug(self):
        """Cache entries must be keyed by (model_slug, query), not just query."""
        SemanticSearch._embedding_cache.clear()

        emb_a = self._search("model_a", [3.0, 4.0])._get_query_embedding("frontmatter")
        emb_b = self._search("model_b", [0.0, 2.0])._get_query_embedding("frontmatter")

        np.testing.assert_allclose(emb_a, [0.6, 0.8])
        np.testing.assert_allclose(emb_b, [0.0, 1.0])
        assert ("model_a", "frontmatter") in SemanticSearch._embedding_cache
        assert ("model_b", "frontmatter") in SemanticSearch._embedding_cache

    def test_same_model_reuses_cached_embedding(self):
        SemanticSearch._embedding_cache.clear()
        initial_hits = SemanticSearch._cache_hits
        search = self._search("test_model", [0.5] * 4)

        search._get_query_embedding("bm25 ranking")
        search._get_query_embedding("bm25 ranking")

        assert SemanticSearch._cache_hits == initial_hits + 1
        assert search.indexer.backend.encode_one.call_count == 1


class TestTopKBounds:
    def test_caps_top_k_at_max(self):
        assert _clamp_top_k(200) == 100

    def test_default_when_zero(self):
        assert _clamp_top_k(0) == 10

    def test_default_when_negative(self):
        assert _clamp_top_k(-5) == 10

    def test_passthrough_valid_value(self):
        assert _clamp_top_k(50) == 50

    def test_custom_default(self):
        assert _clamp_top_k(0, default=20) == 20

    def test_custom_max(self):
        assert _clamp_top_k(200, max_val=50) == 50
