"""Tests for smart search routing and context packets."""

from unittest.mock import MagicMock, patch

from trace_search.search import (
    SearchRoute,
    SmartSearch,
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


def test_smart_search_keeps_strong_keyword_results():
    """Strong BM25 hits should short-circuit before hybrid is consulted."""
    smart = SmartSearch.__new__(SmartSearch)
    smart.keyword = MagicMock()
    smart.hybrid = MagicMock()
    smart.keyword.search.return_value = [_hit(score=3.0)]

    result = smart.search("BM25", top_k=3)

    assert result.route.strategy == "keyword"
    assert not result.route.fallback_used
    smart.hybrid.search.assert_not_called()
    assert result.hits[0]["match_hints"]


def test_smart_search_falls_back_for_weak_keyword_results():
    """Empty BM25 results should trigger hybrid fallback."""
    smart = SmartSearch.__new__(SmartSearch)
    smart.keyword = MagicMock()
    smart.hybrid = MagicMock()
    smart.keyword.search.return_value = []
    smart.hybrid.search.return_value = [
        _hit(path="semantic.md", score=0.7, source="hybrid")
    ]

    result = smart.search("how does semantic ranking work", top_k=5)

    assert result.route.strategy == "hybrid"
    assert result.route.fallback_used
    smart.hybrid.search.assert_called_once()
    assert result.hits[0]["source"] == "hybrid"


def test_smart_search_empty_query_does_not_call_engines():
    smart = SmartSearch.__new__(SmartSearch)
    smart.keyword = MagicMock()
    smart.hybrid = MagicMock()

    result = smart.search("   ", top_k=5)

    assert result.hits == []
    assert result.route.reason == "empty query"
    smart.keyword.search.assert_not_called()
    smart.hybrid.search.assert_not_called()


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


def test_default_search_tool_uses_smart_registry_path(tmp_path):
    from trace_search.search import SmartSearchResult
    from trace_search.server_app import CollectionRegistry, build_multi_mcp

    kb = tmp_path / "docs"
    kb.mkdir()
    _, tools = build_multi_mcp("trace-test", {"docs": kb})

    with patch.object(
        CollectionRegistry,
        "search_smart",
        return_value=SmartSearchResult(
            hits=[_hit()],
            route=SearchRoute(
                strategy="keyword",
                reason="test route",
                fallback_used=False,
            ),
        ),
    ) as search_smart:
        rendered = tools["search"].fn("BM25")

    search_smart.assert_called_once()
    assert "**Selected:** keyword" in rendered


def test_multi_collection_smart_search_batches_neighbor_fetches(tmp_path):
    """Multi-collection smart search should issue one ChromaDB get() per collection,
    not one per hit."""
    from trace_search.search import SmartSearchResult
    from trace_search.server_app import CollectionRegistry

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
        smart = MagicMock()
        smart.search.return_value = SmartSearchResult(
            hits=hits_by_col[name],
            route=SearchRoute(
                strategy="keyword",
                reason="test route",
                fallback_used=False,
            ),
        )
        col._smart = smart

        indexer = MagicMock()
        col._indexer = indexer

    result = registry.search_smart("query", top_k=10, collection=None)

    assert len(result.hits) == 10
    assert {h["collection"] for h in result.hits} == {"kb1", "kb2"}

    kb1_batch = registry.collections["kb1"]._indexer.neighbor_contents_batch
    kb2_batch = registry.collections["kb2"]._indexer.neighbor_contents_batch
    assert kb1_batch.call_count == 1
    assert kb2_batch.call_count == 1
    assert len(kb1_batch.call_args.args[0]) == 5  # one batch per collection


def test_specialist_keyword_tool_bypasses_smart_registry_path(tmp_path):
    from trace_search.server_app import CollectionRegistry, build_multi_mcp

    kb = tmp_path / "docs"
    kb.mkdir()
    _, tools = build_multi_mcp("trace-test", {"docs": kb})

    with (
        patch.object(CollectionRegistry, "search_keyword", return_value=[]) as keyword,
        patch.object(CollectionRegistry, "search_smart") as search_smart,
    ):
        tools["keyword_search"].fn("BM25")

    keyword.assert_called_once()
    search_smart.assert_not_called()
