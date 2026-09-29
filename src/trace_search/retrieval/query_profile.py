"""Query heuristics for adaptive search."""

from __future__ import annotations

import re

LEXICAL_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "for",
        "how",
        "in",
        "is",
        "of",
        "the",
        "to",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
    }
)

# Adaptive search trusts BM25 alone when its top document scores at least this
# multiple of the runner-up. Below it, the lexical evidence does not single out
# one page, and fusing in semantic ranking wins more often than it loses.
BM25_DOMINANCE_MARGIN = 1.3


def _words(query: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9_/-]+", query.lower())


def is_keywordish_query(query: str) -> bool:
    """Return whether a query has strong lexical anchors."""
    words = _words(query)
    if not words:
        return False

    if (
        len(words) <= 4
        and words[0] == "what"
        and len(words) > 1
        and words[1] in {"is", "are"}
    ):
        return True

    if any("_" in word or "/" in word or "-" in word for word in words):
        return True
    if any(any(ch.isdigit() for ch in word) for word in words):
        return True
    if any(word.isupper() and len(word) > 1 for word in query.split()):
        return True

    dense_terms = [word for word in words if word not in LEXICAL_STOPWORDS]
    return len(words) <= 6 and len(dense_terms) == len(words)
