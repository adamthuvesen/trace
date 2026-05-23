"""Tests for canonical index path helpers."""

from pathlib import Path

from trace_search.index_paths import (
    CHROMA_COLLECTION,
    bm25_dir,
    chroma_dir,
    chunk_id,
)


def test_chroma_and_bm25_dirs_use_model_slug() -> None:
    root = Path("/data/indexes")
    assert chroma_dir(root, "minilm") == Path("/data/indexes/.chroma_db_minilm")
    assert bm25_dir(root, "minilm") == Path("/data/indexes/.bm25_index_minilm")


def test_chunk_id_format() -> None:
    assert chunk_id("docs/a.md", 3) == "docs/a.md::3"


def test_chroma_collection_name() -> None:
    assert CHROMA_COLLECTION == "wiki_docs"
