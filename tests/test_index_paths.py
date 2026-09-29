"""Tests for canonical index path helpers."""

from trace_search.indexing.index_paths import chunk_id


def test_chunk_id_format() -> None:
    assert chunk_id("docs/a.md", 3) == "docs/a.md::3"
