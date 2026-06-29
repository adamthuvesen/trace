"""Tests for adaptive search routing and context packets."""

from unittest.mock import MagicMock, patch

from trace_search.retrieval.search import (
    SearchRoute,
    AdaptiveSearch,
    format_context_packets,
)


def _hit(path="doc.md", score=2.0, source="keyword", content="BM25 ranking docs"):
    return {
        "id": f"{path}::0",
        "path": path,
        "title": "Doc",
        "folder": "",
        "content": content,
        "score": score,
        "source": source,
        "chunk_index": 0,
        "chunk_count": 1,
        "breadcrumb": "Doc > Search",
    }


def test_smart_public_aliases_remain_importable():
    import trace_search
    from trace_search.retrieval.search import AdaptiveSearchResult, SmartSearch
    from trace_search.retrieval.search_types import SmartSearchResult

    assert SmartSearch is AdaptiveSearch
    assert trace_search.SmartSearch is AdaptiveSearch
    assert SmartSearchResult is AdaptiveSearchResult
    assert trace_search.SmartSearchResult is AdaptiveSearchResult


def test_adaptive_search_keeps_strong_keyword_results():
    """Strong BM25 hits should short-circuit before hybrid is consulted."""
    adaptive = AdaptiveSearch.__new__(AdaptiveSearch)
    adaptive.keyword = MagicMock()
    adaptive.hybrid = MagicMock()
    adaptive.keyword.search.return_value = [_hit(score=3.0)]

    result = adaptive.search("BM25", top_k=3)

    assert result.route.strategy == "keyword"
    assert not result.route.fallback_used
    adaptive.hybrid.search.assert_not_called()
    assert result.hits[0]["match_hints"]


def test_adaptive_search_falls_back_for_weak_keyword_results():
    """Empty BM25 results should trigger hybrid fallback."""
    adaptive = AdaptiveSearch.__new__(AdaptiveSearch)
    adaptive.keyword = MagicMock()
    adaptive.hybrid = MagicMock()
    adaptive.keyword.search.return_value = []
    adaptive.hybrid.search.return_value = [
        _hit(path="semantic.md", score=0.7, source="hybrid")
    ]

    result = adaptive.search("how does semantic ranking work", top_k=5)

    assert result.route.strategy == "hybrid"
    assert result.route.fallback_used
    adaptive.hybrid.search.assert_called_once()
    assert result.hits[0]["source"] == "hybrid"


def test_adaptive_search_abstains_when_fallback_confidence_is_low():
    """Dense fallback should not return arbitrary neighbors without lexical evidence."""
    adaptive = AdaptiveSearch.__new__(AdaptiveSearch)
    adaptive.keyword = MagicMock()
    adaptive.hybrid = MagicMock()
    adaptive.keyword.search.return_value = []
    adaptive.hybrid.search.return_value = [
        _hit(path="weak.md", score=0.29, source="hybrid")
    ]

    result = adaptive.search(
        "sourdough starter hydration rye flour feeding schedule",
        top_k=5,
    )

    assert result.hits == []
    assert result.route.strategy == "hybrid"
    assert result.route.reason == "hybrid fallback confidence was too low"
    assert result.route.fallback_used


def test_adaptive_search_keeps_confident_fallback_without_keyword_hits():
    adaptive = AdaptiveSearch.__new__(AdaptiveSearch)
    adaptive.keyword = MagicMock()
    adaptive.hybrid = MagicMock()
    adaptive.keyword.search.return_value = []
    adaptive.hybrid.search.return_value = [
        _hit(path="semantic.md", score=0.56, source="hybrid")
    ]

    result = adaptive.search("alternate phrasing for retrieval", top_k=5)

    assert [hit["path"] for hit in result.hits] == ["semantic.md"]
    assert result.route.strategy == "hybrid"
    assert result.route.fallback_used


def test_adaptive_search_does_not_fallback_for_empty_keywordish_query():
    """A keywordish query with no meaningful BM25 hit should abstain."""
    adaptive = AdaptiveSearch.__new__(AdaptiveSearch)
    adaptive.keyword = MagicMock()
    adaptive.hybrid = MagicMock()
    adaptive.keyword.search.return_value = []

    result = adaptive.search("kubernetes pod security policy", top_k=5)

    assert result.hits == []
    assert result.route.strategy == "keyword"
    assert result.route.reason == "keyword query had no meaningful BM25 hits"
    assert not result.route.fallback_used
    adaptive.hybrid.search.assert_not_called()


def test_adaptive_search_falls_back_when_weak_tail_inflates_hit_count():
    """A conceptual query whose top BM25 hits are crowded by a weak tail (a common
    word matching many docs) should fall back instead of trusting BM25's rank."""
    adaptive = AdaptiveSearch.__new__(AdaptiveSearch)
    adaptive.keyword = MagicMock()
    adaptive.hybrid = MagicMock()
    # Top two are close and several weak tail hits (~0.25 of best) pad the count
    # past top_k — raw count would short-circuit, strong-hit count must not.
    adaptive.keyword.search.return_value = [
        _hit(path="wrong.md", score=1.40),
        _hit(path="right.md", score=1.18),
        _hit(path="a.md", score=0.34),
        _hit(path="b.md", score=0.34),
        _hit(path="c.md", score=0.33),
    ]
    adaptive.hybrid.search.return_value = [
        _hit(path="right.md", score=0.7, source="hybrid")
    ]

    result = adaptive.search("how do I set the knowledge base path", top_k=5)

    assert result.route.strategy == "hybrid"
    assert result.route.fallback_used
    adaptive.hybrid.search.assert_called_once()


def test_adaptive_search_falls_back_when_top_hit_is_not_dominant():
    """A conceptual query whose BM25 scores are flat (no dominant hit) is a
    vocabulary-mismatch case with no real keyword anchor — fall back to vectors
    even though every hit clears the strong-hit bar."""
    adaptive = AdaptiveSearch.__new__(AdaptiveSearch)
    adaptive.keyword = MagicMock()
    adaptive.hybrid = MagicMock()
    # Five distinct docs, all "strong" relative to the best, but the top barely
    # edges the runner-up (ratio 1.16) — coincidental matches, not confidence.
    adaptive.keyword.search.return_value = [
        _hit(path="wrong.md", score=1.23),
        _hit(path="b.md", score=1.06),
        _hit(path="c.md", score=0.95),
        _hit(path="d.md", score=0.90),
        _hit(path="e.md", score=0.85),
    ]
    adaptive.hybrid.search.return_value = [
        _hit(path="right.md", score=0.7, source="hybrid")
    ]

    result = adaptive.search(
        "find nearby vectors fast without scanning every one", top_k=5
    )

    assert result.route.strategy == "hybrid"
    assert result.route.fallback_used
    adaptive.hybrid.search.assert_called_once()


def test_adaptive_search_trusts_decisive_conceptual_keyword_hit():
    """A conceptual query with a clear BM25 winner should avoid vector fallback."""
    adaptive = AdaptiveSearch.__new__(AdaptiveSearch)
    adaptive.keyword = MagicMock()
    adaptive.hybrid = MagicMock()
    adaptive.keyword.search.return_value = [
        _hit(path="right.md", score=4.0),
        _hit(path="runner-up.md", score=1.8),
        _hit(path="tail.md", score=1.6),
    ]

    result = adaptive.search("how do agents keep sentences across chunk boundaries")

    assert result.route.strategy == "keyword"
    assert not result.route.fallback_used
    adaptive.hybrid.search.assert_not_called()


def test_adaptive_search_trusts_anchored_conceptual_keyword_hit():
    """File-level BM25 metadata anchors are strong enough to avoid fallback."""
    adaptive = AdaptiveSearch.__new__(AdaptiveSearch)
    adaptive.keyword = MagicMock()
    adaptive.hybrid = MagicMock()
    anchored = _hit(path="right.md", score=1.2)
    anchored["bm25_metadata_overlap"] = 0.25
    adaptive.keyword.search.return_value = [
        anchored,
        _hit(path="runner-up.md", score=1.1),
        _hit(path="tail.md", score=1.0),
    ]

    result = adaptive.search("how does anchored retrieval ranking work")

    assert result.route.strategy == "keyword"
    assert result.route.reason == "conceptual query had an anchored BM25 file hit"
    assert not result.route.fallback_used
    adaptive.hybrid.search.assert_not_called()


def test_adaptive_search_falls_back_for_weak_decisive_keyword_hit():
    """A tiny BM25 score is not trustworthy just because the runner-up is tinier."""
    adaptive = AdaptiveSearch.__new__(AdaptiveSearch)
    adaptive.keyword = MagicMock()
    adaptive.hybrid = MagicMock()
    adaptive.keyword.search.return_value = [
        _hit(path="weak.md", score=0.04),
        _hit(path="weaker.md", score=0.01),
    ]
    adaptive.hybrid.search.return_value = [
        _hit(path="semantic.md", score=0.7, source="hybrid")
    ]

    result = adaptive.search("how do agents keep sentences across chunk boundaries")

    assert result.route.strategy == "hybrid"
    assert result.route.reason == "BM25 best score was very low"
    assert result.route.fallback_used
    adaptive.hybrid.search.assert_called_once()


def test_adaptive_search_empty_query_does_not_call_engines():
    adaptive = AdaptiveSearch.__new__(AdaptiveSearch)
    adaptive.keyword = MagicMock()
    adaptive.hybrid = MagicMock()

    result = adaptive.search("   ", top_k=5)

    assert result.hits == []
    assert result.route.reason == "empty query"
    adaptive.keyword.search.assert_not_called()
    adaptive.hybrid.search.assert_not_called()


def test_collection_smart_alias_uses_adaptive_cache(tmp_path):
    from trace_search.collections.collection_registry import Collection

    collection = Collection(
        name="docs",
        kb_path=tmp_path / "docs",
        index_path=tmp_path / "index",
    )
    adaptive = MagicMock()
    collection._adaptive = adaptive

    assert collection.get_smart() is adaptive


def test_context_packets_group_by_document_and_include_followups():
    hits = [
        _hit(content="BM25 ranking compares exact terms with semantic search."),
        _hit(content="BM25 ranking compares exact terms with semantic search."),
        _hit(path="other.md", content="Semantic search finds related concepts."),
    ]

    rendered = format_context_packets(
        hits,
        query="BM25 ranking",
        route=SearchRoute(
            strategy="keyword",
            reason="BM25 returned strong exact-match results",
            fallback_used=False,
        ),
    )

    assert "**Selected:** keyword" in rendered
    assert rendered.count("### ") == 2
    assert "Matched terms" in rendered
    assert 'get_document(path="doc.md")' in rendered
    assert rendered.count("BM25 ranking compares") == 1


def test_context_packets_include_collection_in_followups():
    hit = _hit(path="shared.md")
    hit["collection"] = "docs"

    rendered = format_context_packets([hit], query="BM25")

    assert 'get_document(path="shared.md", collection="docs")' in rendered


def test_default_search_tool_uses_adaptive_registry_path(tmp_path):
    from trace_search.retrieval.search import AdaptiveSearchResult
    from trace_search.collections.collection_registry import CollectionRegistry
    from trace_search.server.mcp_tools import build_multi_mcp

    kb = tmp_path / "docs"
    kb.mkdir()
    _, tools = build_multi_mcp("trace-test", {"docs": kb})

    with patch.object(
        CollectionRegistry,
        "search_adaptive",
        return_value=AdaptiveSearchResult(
            hits=[_hit()],
            route=SearchRoute(
                strategy="keyword",
                reason="test route",
                fallback_used=False,
            ),
        ),
    ) as search_adaptive:
        rendered = tools["search"].fn("BM25")

    search_adaptive.assert_called_once()
    assert "**Selected:** keyword" in rendered


def test_registry_smart_alias_uses_adaptive_search(tmp_path):
    from trace_search.retrieval.search import AdaptiveSearchResult
    from trace_search.collections.collection_registry import CollectionRegistry

    kb = tmp_path / "docs"
    kb.mkdir()
    registry = CollectionRegistry({"docs": kb})
    expected = AdaptiveSearchResult(
        hits=[_hit()],
        route=SearchRoute(
            strategy="keyword",
            reason="test route",
            fallback_used=False,
        ),
    )

    with patch.object(registry, "search_adaptive", return_value=expected) as adaptive:
        assert registry.search_smart("BM25", 5, "docs") is expected
        assert registry._search("smart", "BM25", 5, "docs") is expected

    assert adaptive.call_count == 2


def test_multi_collection_adaptive_search_batches_neighbor_fetches(tmp_path):
    """Multi-collection adaptive search should issue one ChromaDB get() per collection,
    not one per hit."""
    from trace_search.retrieval.search import AdaptiveSearchResult
    from trace_search.collections.collection_registry import CollectionRegistry

    kb1 = tmp_path / "kb1"
    kb1.mkdir()
    kb2 = tmp_path / "kb2"
    kb2.mkdir()

    registry = CollectionRegistry({"kb1": kb1, "kb2": kb2})
    registry._backend = MagicMock()
    registry._warmed = True

    def make_hits(prefix, n=5):
        return [
            {
                "id": f"{prefix}/doc{i}.md::1",
                "path": f"{prefix}/doc{i}.md",
                "title": f"Doc {i}",
                "folder": prefix,
                "content": f"Content {i}",
                "score": 3.0 - i * 0.1,
                "source": "keyword",
                "chunk_index": 1,
                "chunk_count": 3,
                "breadcrumb": f"{prefix} > Doc {i}",
            }
            for i in range(n)
        ]

    hits_by_col = {"kb1": make_hits("kb1"), "kb2": make_hits("kb2")}

    for name, col in registry.collections.items():
        adaptive = MagicMock()
        adaptive.search.return_value = AdaptiveSearchResult(
            hits=hits_by_col[name],
            route=SearchRoute(
                strategy="keyword",
                reason="test route",
                fallback_used=False,
            ),
        )
        col._adaptive = adaptive

        indexer = MagicMock()
        col._indexer = indexer

    result = registry.search_adaptive("query", top_k=10, collection=None)

    assert len(result.hits) == 10
    assert {h["collection"] for h in result.hits} == {"kb1", "kb2"}

    kb1_batch = registry.collections["kb1"]._indexer.neighbor_contents_batch
    kb2_batch = registry.collections["kb2"]._indexer.neighbor_contents_batch
    assert kb1_batch.call_count == 1
    assert kb2_batch.call_count == 1
    assert len(kb1_batch.call_args.args[0]) == 5  # one batch per collection


def test_specialist_keyword_tool_bypasses_adaptive_registry_path(tmp_path):
    from trace_search.collections.collection_registry import CollectionRegistry
    from trace_search.server.mcp_tools import build_multi_mcp

    kb = tmp_path / "docs"
    kb.mkdir()
    _, tools = build_multi_mcp("trace-test", {"docs": kb})

    with (
        patch.object(CollectionRegistry, "search_keyword", return_value=[]) as keyword,
        patch.object(CollectionRegistry, "search_adaptive") as search_adaptive,
    ):
        tools["keyword_search"].fn("BM25")

    keyword.assert_called_once()
    search_adaptive.assert_not_called()
