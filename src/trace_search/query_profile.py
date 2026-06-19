"""Query classification helpers for hybrid and smart search."""

from __future__ import annotations

import re

QUESTION_STARTERS = frozenset({"what", "how", "where", "when", "why", "which", "who"})
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

# SmartSearch keyword-strength heuristics
BM25_WEAK_BEST_SCORE = 0.05
SMART_KEYWORD_STRENGTH_TOP_K = 3
# A hit counts toward BM25 "confidence" only if its score is at least this
# fraction of the best hit's. A common word in a conceptual query can match many
# documents weakly and inflate the raw hit count; this keeps the long weak tail
# from masquerading as a confident keyword result.
BM25_STRONG_HIT_FRACTION = 0.5
# A conceptual query also needs a clearly dominant top hit to trust BM25. When the
# best score barely edges the runner-up, the lexical match is coincidental — a
# vocabulary-mismatch query with no real keyword anchor — and vector search is the
# safer route.
BM25_DOMINANCE_MARGIN = 1.3

# HybridSearch default semantic weights
WEIGHT_QUESTION = 0.7
WEIGHT_KEYWORD = 0.4


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


def classify_query(query: str) -> tuple[str, float]:
    """Classify query type and return optimal semantic weight."""
    words = _words(query)

    if not words:
        return ("default", WEIGHT_QUESTION)

    if is_keywordish_query(query):
        return ("keyword", WEIGHT_KEYWORD)

    if words[0] in QUESTION_STARTERS:
        return ("question", WEIGHT_QUESTION)

    if len(words) <= 2:
        return ("keyword", WEIGHT_KEYWORD)

    return ("default", WEIGHT_QUESTION)


def is_conceptual_query(query: str) -> bool:
    """Return whether a query likely needs semantic/hybrid retrieval."""
    words = _words(query)
    if not words:
        return False
    if is_keywordish_query(query):
        return False
    if words[0] in QUESTION_STARTERS:
        return True
    return len(words) >= 5
