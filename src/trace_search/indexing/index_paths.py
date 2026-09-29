"""Canonical identifiers for Trace indexes."""

from __future__ import annotations


def chunk_id(path: str, chunk_index: int) -> str:
    """Stable chunk identifier for a document slice."""
    return f"{path}::{chunk_index}"
