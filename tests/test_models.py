"""Tests for SearchHit model."""

from trace_search.models import SearchHit


def test_search_hit_round_trip() -> None:
    original = SearchHit(
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
        collection="wiki",
    )
    restored = SearchHit.from_dict(original.to_dict())
    assert restored == original


def test_search_hit_from_dict_minimal() -> None:
    hit = SearchHit.from_dict(
        {
            "id": "x.md::0",
            "path": "x.md",
            "title": "X",
            "folder": "",
            "content": "body",
            "score": 1.0,
            "source": "keyword",
        }
    )
    assert hit.chunk_index is None
    assert hit.to_dict()["path"] == "x.md"
