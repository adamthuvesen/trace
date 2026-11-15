from __future__ import annotations

import logging
import os
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

import yaml

from tools.eval.metrics import percentile as percentile
from tools.eval.models import (
    DEFAULT_MIN_KEYWORDS,
    EvaluationReport,
    EvaluationScope,
    GoldenQueries,
    GoldenQuery,
    QueryResult,
    SearchMode,
)
from trace_search.retrieval.search_types import SearchHit

if TYPE_CHECKING:
    from trace_search.indexing.wiki_indexer import WikiIndexer
    from trace_search.retrieval.search import (
        AdaptiveSearch,
        HybridSearch,
        KeywordSearch,
        SemanticSearch,
    )

    Searcher = SemanticSearch | KeywordSearch | HybridSearch | AdaptiveSearch
else:
    Searcher = object

logger = logging.getLogger(__name__)

EVAL_DIR = Path(__file__).parent
DEFAULT_GOLDEN_QUERIES_PATH = EVAL_DIR / "golden_queries.yaml"
EXAMPLE_GOLDEN_QUERIES_PATH = EVAL_DIR / "golden_queries.example.yaml"
SEARCH_MODES: tuple[SearchMode, ...] = ("semantic", "bm25", "hybrid", "adaptive")


def get_golden_queries_path() -> Path:
    """Resolve golden-queries YAML (env, then Settings/.env, then default)."""
    override = (os.environ.get("EVAL_GOLDEN_QUERIES") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    from trace_search.config import get_settings

    configured = get_settings().eval_golden_queries
    if configured is not None:
        return configured.expanduser().resolve()
    return DEFAULT_GOLDEN_QUERIES_PATH.resolve()


def _missing_golden_queries_message(path: Path) -> str:
    return (
        f"Golden queries file not found: {path}\n\n"
        "Create one from the template (gitignored by default):\n"
        f"  cp {EXAMPLE_GOLDEN_QUERIES_PATH} {DEFAULT_GOLDEN_QUERIES_PATH}\n\n"
        "Then set KB_PATH to a corpus whose files match expected_path in that YAML, "
        "or set EVAL_GOLDEN_QUERIES to a different file."
    )


def load_golden_queries(
    quick_only: bool = False,
    categories: list[str] | None = None,
    file_types: list[str] | None = None,
    stress_only: bool = False,
    include_stress: bool = False,
    golden_queries_path: Path | None = None,
) -> list[GoldenQuery]:
    """Load golden queries from YAML file with optional filtering.

    By default, queries with ``stress_set: true`` are excluded so ``--quick`` /
    ``--full`` counts stay stable. Use ``--include-stress`` to add them, or
    ``--stress`` to run only the stress subset.
    """
    path = (
        golden_queries_path.expanduser().resolve()
        if golden_queries_path
        else get_golden_queries_path()
    )
    if not path.is_file():
        raise ValueError(_missing_golden_queries_message(path))
    try:
        with path.open() as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in {path}: {e}") from e

    validated = GoldenQueries.model_validate(data)
    queries = []
    for query in validated.queries:
        if stress_only:
            if not query.stress_set:
                continue
        elif not include_stress and query.stress_set:
            continue
        if quick_only and not query.quick_set:
            continue
        if categories and query.category not in categories:
            continue
        if file_types and query.file_type not in file_types:
            continue
        queries.append(query)
    if not queries:
        raise ValueError("No queries match the specified filters")
    return queries


def create_searcher(
    indexer: WikiIndexer,
    search_mode: str,
) -> Searcher:
    from trace_search.retrieval.search import (
        AdaptiveSearch,
        HybridSearch,
        KeywordSearch,
        SemanticSearch,
    )

    if search_mode == "semantic":
        return SemanticSearch(indexer)
    if search_mode == "bm25":
        return KeywordSearch(indexer)
    if search_mode == "hybrid":
        return HybridSearch(indexer)
    if search_mode == "adaptive":
        return AdaptiveSearch(indexer)
    raise ValueError(f"Unknown search mode: {search_mode}")


def _effective_min_keywords(
    query: GoldenQuery,
    global_min: int,
    strict_keywords: bool,
) -> int:
    if query.min_keywords is not None:
        return query.min_keywords
    if strict_keywords and query.expected_keywords:
        return len(query.expected_keywords)
    return global_min


def _keyword_scope_content(
    hits: Sequence[SearchHit],
    *,
    top_k: int,
    strict_keywords_top1: bool,
) -> tuple[str, str]:
    """Return (top_1_lower, scope_lower) for keyword substring checks."""
    top_1 = hits[0].content.lower() if hits else ""
    if strict_keywords_top1 or not hits:
        return top_1, top_1
    scope = " ".join(h.content.lower() for h in hits[:top_k])
    return top_1, scope


def evaluate_query(
    query: GoldenQuery,
    searcher: Searcher,
    search_mode: str,
    top_k: int = 5,
    min_keywords: int = DEFAULT_MIN_KEYWORDS,
    strict_keywords: bool = False,
    strict_keywords_top1: bool = False,
) -> QueryResult:
    """Evaluate a single query and return the result.

    Args:
        query: The golden query to evaluate.
        searcher: The search engine to use.
        search_mode: The search mode (semantic, bm25, hybrid, adaptive).
        top_k: Number of results to retrieve.
        min_keywords: Minimum keywords to count as a hit (unless overridden per query
            or by ``strict_keywords``).
        strict_keywords: Require all listed ``expected_keywords`` to match (or
            ``query.min_keywords`` when set).
        strict_keywords_top1: Evaluate keyword hits using only the top-1 chunk body
            (applies to both top-1 and top-5 keyword metrics).
    """
    need = _effective_min_keywords(query, min_keywords, strict_keywords)

    adaptive_strategy: str | None = None
    adaptive_fallback_used: bool | None = None

    start = time.perf_counter()
    if search_mode == "adaptive":
        response = cast("AdaptiveSearch", searcher).search(query.query, top_k=top_k)
        assert response.route is not None
        hits: Sequence[SearchHit] = response.hits
        adaptive_strategy = response.route.strategy
        adaptive_fallback_used = response.route.fallback_used
    elif search_mode == "bm25":
        hits = cast("KeywordSearch", searcher).search(query.query, max_results=top_k)
    else:
        hits = cast("SemanticSearch | HybridSearch", searcher).search(query.query, top_k=top_k)
    latency_ms = (time.perf_counter() - start) * 1000

    if not hits:
        return QueryResult(
            query_id=query.id,
            query=query.query,
            top_1_path_hit=False,
            top_5_path_hit=False,
            top_1_keyword_hit=False,
            top_5_keyword_hit=False,
            retrieved_path="(no results)",
            retrieved_score=0.0,
            latency_ms=latency_ms,
            keywords_found=[],
            keywords_missing=query.expected_keywords,
            path_first_hit_rank=None,
            path_reciprocal_rank=0.0,
            path_hit_within_max_rank=False,
            adaptive_strategy=adaptive_strategy,
            adaptive_fallback_used=adaptive_fallback_used,
            category=query.category,
            file_type=query.file_type,
        )

    path_first_hit_rank: int | None = None
    for i, h in enumerate(hits[:top_k], start=1):
        if query.matches_path(h.path):
            path_first_hit_rank = i
            break

    reciprocal = 1.0 / path_first_hit_rank if path_first_hit_rank else 0.0
    max_rank = query.max_rank if query.max_rank is not None else top_k
    path_hit_within_max_rank = path_first_hit_rank is not None and path_first_hit_rank <= max_rank

    top_1_path = hits[0].path
    top_1_path_hit = query.matches_path(top_1_path)

    top_5_path_hit = any(query.matches_path(h.path) for h in hits[:5])

    top_1_content, scope_content = _keyword_scope_content(
        hits, top_k=top_k, strict_keywords_top1=strict_keywords_top1
    )
    top_1_keywords = [k for k in query.expected_keywords if k.lower() in top_1_content]
    top_1_keyword_hit = len(top_1_keywords) >= need

    top_5_keywords = [k for k in query.expected_keywords if k.lower() in scope_content]
    top_5_keyword_hit = len(top_5_keywords) >= need

    return QueryResult(
        query_id=query.id,
        query=query.query,
        top_1_path_hit=top_1_path_hit,
        top_5_path_hit=top_5_path_hit,
        top_1_keyword_hit=top_1_keyword_hit,
        top_5_keyword_hit=top_5_keyword_hit,
        retrieved_path=top_1_path,
        retrieved_score=hits[0].evidence.score,
        latency_ms=latency_ms,
        keywords_found=top_5_keywords,
        keywords_missing=[k for k in query.expected_keywords if k.lower() not in scope_content],
        path_first_hit_rank=path_first_hit_rank,
        path_reciprocal_rank=reciprocal,
        path_hit_within_max_rank=path_hit_within_max_rank,
        adaptive_strategy=adaptive_strategy,
        adaptive_fallback_used=adaptive_fallback_used,
        category=query.category,
        file_type=query.file_type,
    )


def run_evaluation(
    indexer: WikiIndexer,
    search_mode: str = "hybrid",
    quick_only: bool = False,
    categories: list[str] | None = None,
    file_types: list[str] | None = None,
    top_k: int = 5,
    stress_only: bool = False,
    include_stress: bool = False,
    strict_keywords: bool = False,
    strict_keywords_top1: bool = False,
    golden_queries_path: Path | None = None,
) -> EvaluationReport:
    """Run the full evaluation and return a report."""
    from tools.eval.provenance import build_manifest
    from trace_search.indexing.embedding_warmup import warm_embedding_model
    from trace_search.retrieval.search import SemanticSearch

    min_keywords = DEFAULT_MIN_KEYWORDS
    if search_mode not in SEARCH_MODES:
        raise ValueError(f"Unknown search mode: {search_mode}")
    if type(top_k) is not int or top_k < 1:
        raise ValueError("top_k must be a positive integer")
    if strict_keywords_top1 and not strict_keywords:
        raise ValueError("strict_keywords_top1 requires strict_keywords")

    queries = load_golden_queries(
        quick_only=quick_only,
        categories=categories,
        file_types=file_types,
        stress_only=stress_only,
        include_stress=include_stress,
        golden_queries_path=golden_queries_path,
    )

    if not queries:
        raise ValueError("No queries match the specified filters")

    logger.info("Running evaluation with %d queries (mode: %s)", len(queries), search_mode)

    manifest = build_manifest(
        indexer,
        queries,
        scope=EvaluationScope(
            quick_only=quick_only,
            categories=sorted(categories or []),
            file_types=sorted(file_types or []),
            stress_only=stress_only,
            include_stress=include_stress,
        ),
        search_mode=search_mode,
        top_k=top_k,
        min_keywords=min_keywords,
        strict_keywords=strict_keywords,
        strict_keywords_top1=strict_keywords_top1,
    )
    searcher = create_searcher(indexer, search_mode)
    warm_embedding_model(indexer.backend)

    # Clear embedding cache for consistent per-query timing
    SemanticSearch.clear_embedding_cache()

    results: list[QueryResult] = []
    for i, query in enumerate(queries, 1):
        result = evaluate_query(
            query,
            searcher,
            search_mode,
            top_k,
            min_keywords,
            strict_keywords=strict_keywords,
            strict_keywords_top1=strict_keywords_top1,
        )
        results.append(result)

        status = (
            "HIT" if result.top_1_path_hit else ("PARTIAL" if result.top_5_path_hit else "MISS")
        )
        logger.debug(
            "[%d/%d] %s: %s - %s",
            i,
            len(queries),
            status,
            query.query[:40],
            result.retrieved_path[:50],
        )

    return EvaluationReport.from_results(
        timestamp=datetime.now(UTC).isoformat(),
        manifest=manifest,
        results=results,
    )
