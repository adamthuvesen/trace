"""Query classification helpers for hybrid and smart search."""

from __future__ import annotations

QUESTION_STARTERS = frozenset(
    {"what", "how", "where", "when", "why", "which", "who"}
)

# SmartSearch keyword-strength heuristics
BM25_WEAK_BEST_SCORE = 0.05
SMART_KEYWORD_STRENGTH_TOP_K = 3

# HybridSearch default semantic weights
WEIGHT_QUESTION = 0.7
WEIGHT_KEYWORD = 0.4


def classify_query(query: str) -> tuple[str, float]:
    """Classify query type and return optimal semantic weight."""
    query_lower = query.lower().strip()
    words = query_lower.split()

    if not words:
        return ("default", WEIGHT_QUESTION)

    if words[0] in QUESTION_STARTERS:
        return ("question", WEIGHT_QUESTION)

    if len(words) <= 2:
        return ("keyword", WEIGHT_KEYWORD)

    return ("default", WEIGHT_QUESTION)


def is_conceptual_query(query: str) -> bool:
    """Return whether a query likely needs semantic/hybrid retrieval."""
    words = query.lower().strip().split()
    if not words:
        return False
    if words[0] in QUESTION_STARTERS:
        return True
    return len(words) >= 5
