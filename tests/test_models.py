"""Tests for SearchHit model."""

from trace_search.retrieval.models import SearchHit


def test_search_hit_to_dict_includes_set_fields() -> None:
    hit = SearchHit(
        id="docs/a.md::0",
        path="docs/a.md",
        title="A",
        folder="docs",
        content="hello world",
        score=0.9,
        source="semantic",
        chunk_index=0,
        chunk_count=2,
        breadcrumb="A > Section",
        extension=".md",
        source_mtime=1_700_000_000.0,
        match_hints=["title matches: hello"],
        collection="docs",
    )
    data = hit.to_dict()
    assert data["path"] == "docs/a.md"
    assert data["chunk_index"] == 0
    assert data["breadcrumb"] == "A > Section"
    assert data["match_hints"] == ["title matches: hello"]
    assert data["collection"] == "docs"


def test_search_hit_to_dict_omits_unset_optionals() -> None:
    hit = SearchHit(
        id="x.md",
        path="x.md",
        title="X",
        folder="",
        content="body",
        score=1.0,
        source="keyword",
    )
    data = hit.to_dict()
    assert data["path"] == "x.md"
    assert "chunk_index" not in data
    assert "rerank_score" not in data
    assert "collection" not in data
