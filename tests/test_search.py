"""Tests for search module."""

from typing import get_type_hints

from trace_search.config import settings
from trace_search.retrieval.query_profile import (
    WEIGHT_KEYWORD,
    WEIGHT_QUESTION,
    classify_query,
    is_conceptual_query,
    is_keywordish_query,
)
from trace_search.retrieval.search import (
    _BM25_MIN_FILE_FETCH,
    HybridSearch,
    KeywordSearch,
    SearchFilters,
    _clamp_top_k,
    _keyword_fetch_size,
    _semantic_fetch_size,
    _semantic_lexical_boost,
)
from trace_search.retrieval.search_types import SearchRoute


class TestHybridSearchQueryClassification:
    """Exercises shared query_profile.classify_query."""

    @staticmethod
    def _classify(query: str) -> tuple[str, float]:
        return classify_query(query)

    def test_question_classified_as_question(self):
        query_type, weight = self._classify("How does semantic ranking work?")
        assert query_type == "question"
        assert weight == WEIGHT_QUESTION

    def test_lazy_reranker_type_hints_resolve_at_runtime(self):
        assert "_reranker" in get_type_hints(HybridSearch)
        assert "return" in get_type_hints(HybridSearch._get_reranker)
        assert "filters" in get_type_hints(SearchRoute)

    def test_short_definition_classified_as_keyword(self):
        query_type, weight = self._classify("What is BM25?")
        assert query_type == "keyword"
        assert weight == WEIGHT_KEYWORD

    def test_short_keyword_query_classified_as_keyword(self):
        query_type, weight = self._classify("frontmatter")
        assert query_type == "keyword"
        assert weight == WEIGHT_KEYWORD

        query_type, weight = self._classify("heading chunking")
        assert query_type == "keyword"

    def test_short_acronym_query_classified_as_keyword(self):
        """Acronyms should not trigger expansion; routed as plain keyword."""
        query_type, weight = self._classify("RRF")
        assert query_type == "keyword"
        assert weight == WEIGHT_KEYWORD

    def test_long_query_classified_as_default(self):
        query_type, weight = self._classify(
            "compare semantic and keyword search behavior"
        )
        assert query_type == "default"
        assert weight == WEIGHT_QUESTION

    def test_weight_constants_defined(self):
        assert WEIGHT_KEYWORD == 0.4
        assert WEIGHT_QUESTION == 0.7

    def test_question_weight_favors_semantic(self):
        assert WEIGHT_QUESTION > 0.5

    def test_keyword_weight_favors_bm25(self):
        assert WEIGHT_KEYWORD < 0.5

    def test_weights_in_valid_range(self):
        weights = [WEIGHT_KEYWORD, WEIGHT_QUESTION]
        for w in weights:
            assert 0 <= w <= 1, f"Weight {w} should be between 0 and 1"

    def test_identifier_query_classified_as_keywordish(self):
        assert is_keywordish_query("HTTP 429 Retry-After burst limit")
        assert not is_conceptual_query("HTTP 429 Retry-After burst limit")
        assert self._classify("HTTP 429 Retry-After burst limit")[1] == WEIGHT_KEYWORD

    def test_dense_noun_phrase_classified_as_keywordish(self):
        query = "term frequency saturation document length normalization"

        assert is_keywordish_query(query)
        assert not is_conceptual_query(query)
        assert self._classify(query)[1] == WEIGHT_KEYWORD


class TestEmptyCorpusSearch:
    def test_empty_corpus_returns_empty_list(self):
        from unittest.mock import MagicMock, PropertyMock

        from trace_search.retrieval.search import KeywordSearch

        mock_indexer = MagicMock()
        type(mock_indexer).bm25 = PropertyMock(return_value=MagicMock())
        type(mock_indexer).bm25_corpus = PropertyMock(return_value=[])

        ks = KeywordSearch(mock_indexer)
        result = ks.search("anything")
        assert result == []


class TestKeywordSearchAggregation:
    class FakeBM25:
        def __init__(self, scores):
            self.scores = scores
            self.fetch_size = None

        def retrieve(self, _query_tokens, k):
            self.fetch_size = k
            return [list(range(len(self.scores)))], [self.scores]

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
        class FakeIndexer:
            bm25 = TestKeywordSearchAggregation.FakeBM25([10.0, 9.8, 9.6])
            bm25_corpus = [
                TestKeywordSearchAggregation._metadata("wrong.md", "Wrong", 0),
                TestKeywordSearchAggregation._metadata("right.md", "Alpha", 0),
                TestKeywordSearchAggregation._metadata("right.md", "Alpha", 1),
            ]

        hits = KeywordSearch(FakeIndexer()).search("alpha", max_results=1)

        assert [hit["path"] for hit in hits] == ["right.md"]
        assert hits[0]["bm25_file_support"] == 2
        assert FakeIndexer.bm25.fetch_size == 3

    def test_keyword_fetch_size_oversamples_files_even_with_filters(self):
        # File-level aggregation needs a deep chunk pool to cover enough distinct
        # files; a path filter must not shrink it below the file-oversample floor.
        wiki = SearchFilters(path_prefix=("wiki/",))
        assert _keyword_fetch_size(10, SearchFilters()) >= _BM25_MIN_FILE_FETCH
        assert _keyword_fetch_size(10, wiki) >= _BM25_MIN_FILE_FETCH
        assert _keyword_fetch_size(10, wiki) >= _keyword_fetch_size(10, SearchFilters())

    def test_navigational_hub_demoted_below_content_page(self):
        # index.md and a content page tie on best chunk score; the content page
        # should win because the hub is navigational, not an answer.
        class FakeIndexer:
            bm25 = TestKeywordSearchAggregation.FakeBM25([6.0, 6.0])
            bm25_corpus = [
                TestKeywordSearchAggregation._metadata(
                    "notes/index.md", "Alpha index", 0
                ),
                TestKeywordSearchAggregation._metadata("notes/alpha.md", "Alpha", 0),
            ]

        hits = KeywordSearch(FakeIndexer()).search("alpha", max_results=2)
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

        class FakeIndexer:
            bm25 = TestKeywordSearchAggregation.FakeBM25([7.5] + [6.0] * 20)
            bm25_corpus = [strong, *weak_chunks]

        hits = KeywordSearch(FakeIndexer()).search("zeta", max_results=2)
        assert hits[0]["path"] == "strong.md"
        assert hits[0]["score"] > hits[1]["score"]

    def test_keyword_search_drops_weak_hits_without_metadata_anchor(self):
        class FakeIndexer:
            bm25 = TestKeywordSearchAggregation.FakeBM25([5.0])
            bm25_corpus = TestKeywordSearchAggregation._large_corpus_with(
                TestKeywordSearchAggregation._metadata("unrelated.md", "Unrelated", 0)
            )

        hits = KeywordSearch(FakeIndexer()).search(
            "kubernetes pod security policy",
            max_results=5,
        )

        assert hits == []

    def test_keyword_search_keeps_weak_hits_with_strong_metadata_anchor(self):
        class FakeIndexer:
            bm25 = TestKeywordSearchAggregation.FakeBM25([5.0])
            bm25_corpus = TestKeywordSearchAggregation._large_corpus_with(
                TestKeywordSearchAggregation._metadata(
                    "ops/kubernetes-pod-policy.md",
                    "Kubernetes pod policy",
                    0,
                )
            )

        hits = KeywordSearch(FakeIndexer()).search(
            "kubernetes pod security policy",
            max_results=5,
        )

        assert [hit["path"] for hit in hits] == ["ops/kubernetes-pod-policy.md"]

    def test_keyword_search_drops_weak_hits_with_only_tiny_metadata_overlap(self):
        class FakeIndexer:
            bm25 = TestKeywordSearchAggregation.FakeBM25([5.5])
            bm25_corpus = TestKeywordSearchAggregation._large_corpus_with(
                TestKeywordSearchAggregation._metadata(
                    "archive/unrelated.md",
                    "Unrelated note",
                    0,
                )
            )

        hits = KeywordSearch(FakeIndexer()).search(
            "kubernetes pod security policy",
            max_results=5,
        )

        assert hits == []


class TestSemanticFetchSize:
    def test_semantic_fetch_size_never_drops_below_top_k(self):
        assert _semantic_fetch_size(100, SearchFilters()) >= 100


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

        assert _semantic_lexical_boost(query, exact) > _semantic_lexical_boost(
            query, partial
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

        assert _semantic_lexical_boost(query, rate_limit) > _semantic_lexical_boost(
            query, retryable
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
    def test_cache_key_includes_model_slug(self):
        """Cache entries must be keyed by (model_slug, query), not just query."""
        from unittest.mock import MagicMock
        from trace_search.retrieval.search import SemanticSearch

        SemanticSearch._embedding_cache.clear()

        mock_collection = MagicMock()
        fake_embed_a = tuple([0.1] * 384)
        fake_embed_b = tuple([0.9] * 768)

        class FakeVec(list):
            def tolist(self):
                return list(self)

        instance_a = SemanticSearch.__new__(SemanticSearch)
        instance_a.collection = mock_collection
        instance_a._model_slug = "model_a"
        instance_a.backend = MagicMock()
        instance_a.backend.encode_one.return_value = FakeVec(fake_embed_a)

        instance_b = SemanticSearch.__new__(SemanticSearch)
        instance_b.collection = mock_collection
        instance_b._model_slug = "model_b"
        instance_b.backend = MagicMock()
        instance_b.backend.encode_one.return_value = FakeVec(fake_embed_b)

        emb_a = instance_a._get_query_embedding("frontmatter")
        emb_b = instance_b._get_query_embedding("frontmatter")

        assert emb_a == list(fake_embed_a)
        assert emb_b == list(fake_embed_b)
        assert emb_a != emb_b
        assert ("model_a", "frontmatter") in SemanticSearch._embedding_cache
        assert ("model_b", "frontmatter") in SemanticSearch._embedding_cache

    def test_same_model_reuses_cached_embedding(self):
        from unittest.mock import MagicMock
        from trace_search.retrieval.search import SemanticSearch

        SemanticSearch._embedding_cache.clear()
        initial_hits = SemanticSearch._cache_hits

        fake_embed = tuple([0.5] * 384)

        class FakeVec(list):
            def tolist(self):
                return list(self)

        instance = SemanticSearch.__new__(SemanticSearch)
        instance.collection = MagicMock()
        instance._model_slug = "test_model"
        instance.backend = MagicMock()
        instance.backend.encode_one.return_value = FakeVec(fake_embed)

        instance._get_query_embedding("bm25 ranking")
        instance._get_query_embedding("bm25 ranking")

        assert SemanticSearch._cache_hits == initial_hits + 1
        assert instance.backend.encode_one.call_count == 1


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
