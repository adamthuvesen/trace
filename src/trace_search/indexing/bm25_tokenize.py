"""Shared BM25 tokenization helpers."""

from __future__ import annotations

import bm25s
import Stemmer
from bm25s.tokenization import Tokenized

_stemmer: Stemmer.Stemmer | None = None


def english_stemmer() -> Stemmer.Stemmer:
    """Return a process-wide English stemmer for BM25 queries."""
    global _stemmer
    if _stemmer is None:
        _stemmer = Stemmer.Stemmer("english")
    return _stemmer


def tokenize_keywords(text: str) -> list[list[str]] | Tokenized:
    """Tokenize a keyword query for BM25 retrieval."""
    return bm25s.tokenize(
        [text],
        stopwords="en",
        stemmer=english_stemmer(),
        show_progress=False,
    )
