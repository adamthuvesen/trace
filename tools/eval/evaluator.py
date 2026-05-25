"""Evaluation harness for wiki search."""

from __future__ import annotations

import logging
import math
import os
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from tools.eval.models import (
    CategoryMetrics,
    EvaluationReport,
    FileTypeMetrics,
    GoldenQuery,
    QueryResult,
)

if TYPE_CHECKING:
    from trace_search.indexer import WikiIndexer
    from trace_search.search import (
        HybridSearch,
        KeywordSearch,
        SemanticSearch,
        SmartSearch,
    )

    Searcher = SemanticSearch | KeywordSearch | HybridSearch | SmartSearch
else:
    Searcher = object

logger = logging.getLogger(__name__)

EVAL_DIR = Path(__file__).parent
DEFAULT_GOLDEN_QUERIES_PATH = EVAL_DIR / "golden_queries.yaml"
EXAMPLE_GOLDEN_QUERIES_PATH = EVAL_DIR / "golden_queries.example.yaml"


def get_golden_queries_path() -> Path:
    """Resolve golden-queries YAML (env, then Settings/.env, then default)."""
    override = (os.environ.get("EVAL_GOLDEN_QUERIES") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    try:
        from trace_search.config import settings

        if settings.eval_golden_queries is not None:
            return settings.eval_golden_queries.expanduser().resolve()
    except Exception:
        pass
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
) -> list[GoldenQuery]:
    """Load golden queries from YAML file with optional filtering.

    By default, queries with ``stress_set: true`` are excluded so ``--quick`` /
    ``--full`` counts stay stable. Use ``--include-stress`` to add them, or
    ``--stress`` to run only the stress subset.
    """
    path = get_golden_queries_path()
    if not path.is_file():
        raise ValueError(_missing_golden_queries_message(path))
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in {path}: {e}") from e

    if not isinstance(data, dict) or not isinstance(data.get("queries"), list):
        raise ValueError(f"{path} must contain a top-level 'queries' list")

    queries = []
    for i, q in enumerate(data.get("queries", [])):
        try:
            query = GoldenQuery.from_dict(q)
        except KeyError as e:
            raise ValueError(f"Query at index {i} missing required field: {e}") from e
        except TypeError as e:
            raise ValueError(f"Query at index {i} has invalid data: {e}") from e

        if stress_only:
            if not query.stress_set:
                continue
        elif not include_stress and query.stress_set:
            continue

        # Apply filters
        if quick_only and not query.quick_set:
            continue
        if categories and query.category not in categories:
            continue
        if file_types and query.file_type not in file_types:
            continue

        queries.append(query)

    return queries


def create_searcher(
    indexer: WikiIndexer,
    search_mode: str,
) -> Searcher:
    from trace_search.search import (
        HybridSearch,
        KeywordSearch,
        SemanticSearch,
        SmartSearch,
    )

    if search_mode == "semantic":
        return SemanticSearch(indexer.collection, indexer.backend)
    if search_mode == "bm25":
        return KeywordSearch(indexer)
    if search_mode == "hybrid":
        return HybridSearch(indexer, indexer.backend)
    if search_mode == "smart":
        return SmartSearch(indexer, indexer.backend)
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
    hits: list[dict],
    *,
    top_k: int,
    strict_keywords_top1: bool,
) -> tuple[str, str]:
    """Return (top_1_lower, scope_lower) for keyword substring checks."""
    top_1 = hits[0]["content"].lower() if hits else ""
    if strict_keywords_top1 or not hits:
        return top_1, top_1
    scope = " ".join(h["content"].lower() for h in hits[:top_k])
    return top_1, scope


def percentile(sorted_values: list[float], pct: float) -> float:
    """Inclusive linear percentile bounded by observed min/max."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (len(sorted_values) - 1) * (pct / 100)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return sorted_values[lower]
    weight = rank - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def evaluate_query(
    query: GoldenQuery,
    searcher: Searcher,
    search_mode: str,
    top_k: int = 5,
    min_keywords: int = 2,
    strict_keywords: bool = False,
    strict_keywords_top1: bool = False,
) -> QueryResult:
    """Evaluate a single query and return the result.

    Args:
        query: The golden query to evaluate.
        searcher: The search engine to use.
        search_mode: The search mode (semantic, bm25, hybrid).
        top_k: Number of results to retrieve.
        min_keywords: Minimum keywords to count as a hit (unless overridden per query
            or by ``strict_keywords``).
        strict_keywords: Require all listed ``expected_keywords`` to match (or
            ``query.min_keywords`` when set).
        strict_keywords_top1: Evaluate keyword hits using only the top-1 chunk body
            (applies to both top-1 and top-5 keyword metrics).
    """
    need = _effective_min_keywords(query, min_keywords, strict_keywords)

    smart_strategy: str | None = None
    smart_fallback_used: bool | None = None

    start = time.perf_counter()
    if search_mode == "smart":
        from trace_search.search_types import SmartSearchResult

        smart_result = searcher.search(query.query, top_k=top_k)
        assert isinstance(smart_result, SmartSearchResult)
        hits = smart_result.hits
        smart_strategy = smart_result.route.strategy
        smart_fallback_used = smart_result.route.fallback_used
    elif search_mode == "bm25":
        hits = searcher.search(query.query, max_results=top_k)
    else:
        hits = searcher.search(query.query, top_k=top_k)
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
            smart_strategy=smart_strategy,
            smart_fallback_used=smart_fallback_used,
        )

    path_first_hit_rank: int | None = None
    for i, h in enumerate(hits[:top_k], start=1):
        if query.matches_path(h["path"]):
            path_first_hit_rank = i
            break

    reciprocal = 1.0 / path_first_hit_rank if path_first_hit_rank else 0.0
    max_rank = query.max_rank if query.max_rank is not None else top_k
    path_hit_within_max_rank = (
        path_first_hit_rank is not None and path_first_hit_rank <= max_rank
    )

    top_1_path = hits[0]["path"]
    top_1_path_hit = query.matches_path(top_1_path)

    top_5_path_hit = any(query.matches_path(h["path"]) for h in hits[:5])

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
        retrieved_score=hits[0].get("score", 0.0),
        latency_ms=latency_ms,
        keywords_found=top_5_keywords,
        keywords_missing=[
            k for k in query.expected_keywords if k.lower() not in scope_content
        ],
        path_first_hit_rank=path_first_hit_rank,
        path_reciprocal_rank=reciprocal,
        path_hit_within_max_rank=path_hit_within_max_rank,
        smart_strategy=smart_strategy,
        smart_fallback_used=smart_fallback_used,
    )


def compute_category_metrics(
    queries: list[GoldenQuery],
    results: list[QueryResult],
) -> dict[str, CategoryMetrics]:
    """Compute metrics grouped by category."""
    by_category: dict[str, list[tuple[GoldenQuery, QueryResult]]] = defaultdict(list)
    query_map = {q.id: q for q in queries}

    for result in results:
        query = query_map.get(result.query_id)
        if query:
            by_category[query.category].append((query, result))

    metrics = {}
    for category, items in by_category.items():
        query_count = len(items)
        top_1_path_hits = sum(1 for _, r in items if r.top_1_path_hit)
        top_5_path_hits = sum(1 for _, r in items if r.top_5_path_hit)
        top_1_keyword_hits = sum(1 for _, r in items if r.top_1_keyword_hit)
        top_5_keyword_hits = sum(1 for _, r in items if r.top_5_keyword_hit)
        avg_latency = statistics.mean(r.latency_ms for _, r in items) if items else 0.0

        metrics[category] = CategoryMetrics(
            category=category,
            query_count=query_count,
            top_1_path_hits=top_1_path_hits,
            top_5_path_hits=top_5_path_hits,
            top_1_keyword_hits=top_1_keyword_hits,
            top_5_keyword_hits=top_5_keyword_hits,
            avg_latency_ms=avg_latency,
        )

    return metrics


def compute_file_type_metrics(
    queries: list[GoldenQuery],
    results: list[QueryResult],
) -> dict[str, FileTypeMetrics]:
    """Compute metrics grouped by file type."""
    by_type: dict[str, list[tuple[GoldenQuery, QueryResult]]] = defaultdict(list)
    query_map = {q.id: q for q in queries}

    for result in results:
        query = query_map.get(result.query_id)
        if query:
            by_type[query.file_type].append((query, result))

    metrics = {}
    for file_type, items in by_type.items():
        query_count = len(items)
        top_1_path_hits = sum(1 for _, r in items if r.top_1_path_hit)
        top_5_path_hits = sum(1 for _, r in items if r.top_5_path_hit)
        avg_latency = statistics.mean(r.latency_ms for _, r in items) if items else 0.0

        metrics[file_type] = FileTypeMetrics(
            file_type=file_type,
            query_count=query_count,
            top_1_path_hits=top_1_path_hits,
            top_5_path_hits=top_5_path_hits,
            avg_latency_ms=avg_latency,
        )

    return metrics


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
) -> EvaluationReport:
    """Run the full evaluation and return a report."""
    from trace_search.config import settings
    from trace_search.search import SemanticSearch

    from tools.eval import load_thresholds

    thresholds = load_thresholds()
    min_keywords = thresholds.get("keyword_match", {}).get("min_keywords", 2)

    queries = load_golden_queries(
        quick_only=quick_only,
        categories=categories,
        file_types=file_types,
        stress_only=stress_only,
        include_stress=include_stress,
    )

    if not queries:
        raise ValueError("No queries match the specified filters")

    logger.info(
        "Running evaluation with %d queries (mode: %s)", len(queries), search_mode
    )

    searcher = create_searcher(indexer, search_mode)

    # Clear embedding cache for consistent per-query timing
    SemanticSearch._embedding_cache.clear()

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
            "HIT"
            if result.top_1_path_hit
            else ("PARTIAL" if result.top_5_path_hit else "MISS")
        )
        logger.debug(
            "[%d/%d] %s: %s - %s",
            i,
            len(queries),
            status,
            query.query[:40],
            result.retrieved_path[:50],
        )

    total = len(results)
    top_1_path_hits = sum(1 for r in results if r.top_1_path_hit)
    top_5_path_hits = sum(1 for r in results if r.top_5_path_hit)
    top_1_keyword_hits = sum(1 for r in results if r.top_1_keyword_hit)
    top_5_keyword_hits = sum(1 for r in results if r.top_5_keyword_hit)
    mean_rr = (
        statistics.mean(r.path_reciprocal_rank for r in results) if results else 0.0
    )
    within_max = sum(1 for r in results if r.path_hit_within_max_rank)
    within_max_acc = within_max / total if total > 0 else 0.0

    # Compute latency percentiles bounded by observed values, even for tiny samples.
    latencies = sorted(r.latency_ms for r in results)
    p50 = percentile(latencies, 50)
    p95 = percentile(latencies, 95)
    p99 = percentile(latencies, 99)

    by_category = compute_category_metrics(queries, results)
    by_file_type = compute_file_type_metrics(queries, results)

    smart_fallback_rate: float | None = None
    if search_mode == "smart":
        fallback_flags = [
            r.smart_fallback_used for r in results if r.smart_fallback_used is not None
        ]
        if fallback_flags:
            smart_fallback_rate = sum(1 for flag in fallback_flags if flag) / len(
                fallback_flags
            )

    return EvaluationReport(
        timestamp=datetime.now(timezone.utc).isoformat(),
        search_mode=search_mode,
        embedding_model=settings.embedding_model,
        total_queries=total,
        quick_set_only=quick_only,
        top_1_path_accuracy=top_1_path_hits / total if total > 0 else 0.0,
        top_5_path_accuracy=top_5_path_hits / total if total > 0 else 0.0,
        top_1_keyword_accuracy=top_1_keyword_hits / total if total > 0 else 0.0,
        top_5_keyword_accuracy=top_5_keyword_hits / total if total > 0 else 0.0,
        latency_p50_ms=p50,
        latency_p95_ms=p95,
        latency_p99_ms=p99,
        latency_mean_ms=statistics.mean(latencies) if latencies else 0.0,
        by_category=by_category,
        by_file_type=by_file_type,
        results=results,
        regression=None,
        mean_reciprocal_rank=mean_rr,
        within_max_rank_path_accuracy=within_max_acc,
        include_stress=(
            stress_only or (include_stress and any(q.stress_set for q in queries))
        ),
        stress_only=stress_only,
        strict_keywords=strict_keywords,
        strict_keywords_top1=strict_keywords_top1,
        smart_fallback_rate=smart_fallback_rate,
    )
