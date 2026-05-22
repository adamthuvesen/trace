"""Shared BM25 tokenization helpers."""

from __future__ import annotations

import bm25s
import Stemmer

_STEMMER: Stemmer.Stemmer | None = None


def english_stemmer() -> Stemmer.Stemmer:
    """Return a process-wide English stemmer for BM25 queries."""
    global _STEMMER
    if _STEMMER is None:
        _STEMMER = Stemmer.Stemmer("english")
    return _STEMMER


def tokenize_keywords(text: str) -> object:
    """Tokenize a keyword query for BM25 retrieval."""
    return bm25s.tokenize(
        [text],
        stopwords="en",
        stemmer=english_stemmer(),
    )
