"""Canonical paths and identifiers for Trace indexes."""

from __future__ import annotations

from pathlib import Path

CHROMA_COLLECTION = "wiki_docs"


def chroma_dir(index_root: Path, model_slug: str) -> Path:
    """Directory for a model-specific Chroma persistent store."""
    return index_root / f".chroma_db_{model_slug}"


def bm25_dir(index_root: Path, model_slug: str) -> Path:
    """Directory for a model-specific BM25 index artifacts."""
    return index_root / f".bm25_index_{model_slug}"


def chunk_id(path: str, chunk_index: int) -> str:
    """Stable Chroma/BM25 chunk identifier for a document slice."""
    return f"{path}::{chunk_index}"
