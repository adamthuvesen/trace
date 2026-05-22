"""Data models for the evaluation suite."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class GoldenQuery:
    """A golden test query with expected answer location."""

    id: str
    query: str
    category: str
    expected_path: str
    expected_keywords: list[str]
    file_type: str = ".md"
    alternate_paths: list[str] = field(default_factory=list)
    quick_set: bool = False
    description: str = ""
    difficulty: str = "easy"
    stress_set: bool = False
    min_keywords: int | None = None
    max_rank: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GoldenQuery:
        return cls(
            id=data["id"],
            query=data["query"],
            category=data["category"],
            expected_path=data["expected_path"],
            expected_keywords=data.get("expected_keywords", []),
            file_type=data.get("file_type", ".md"),
            alternate_paths=data.get("alternate_paths", []),
            quick_set=data.get("quick_set", False),
            description=data.get("description", ""),
            difficulty=data.get("difficulty", "easy"),
            stress_set=data.get("stress_set", False),
            min_keywords=data.get("min_keywords"),
            max_rank=data.get("max_rank"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "query": self.query,
            "category": self.category,
            "expected_path": self.expected_path,
            "expected_keywords": self.expected_keywords,
            "file_type": self.file_type,
            "alternate_paths": self.alternate_paths,
            "quick_set": self.quick_set,
            "description": self.description,
            "difficulty": self.difficulty,
            "stress_set": self.stress_set,
            "min_keywords": self.min_keywords,
            "max_rank": self.max_rank,
        }

    def matches_path(self, retrieved_path: str) -> bool:
        """Check if the retrieved path matches expected or alternate paths."""
        retrieved_normalized = Path(retrieved_path).as_posix().lower()
        expected_normalized = Path(self.expected_path).as_posix().lower()

        if retrieved_normalized == expected_normalized:
            return True

        for alt_path in self.alternate_paths:
            alt_normalized = Path(alt_path).as_posix().lower()
            if retrieved_normalized == alt_normalized:
                return True

        return False


@dataclass
class QueryResult:
    """Result from evaluating a single query."""

    query_id: str
    query: str
    top_1_path_hit: bool
    top_5_path_hit: bool
    top_1_keyword_hit: bool
    top_5_keyword_hit: bool
    retrieved_path: str
    retrieved_score: float
    latency_ms: float
    keywords_found: list[str] = field(default_factory=list)
    keywords_missing: list[str] = field(default_factory=list)
    path_first_hit_rank: int | None = None
    path_reciprocal_rank: float = 0.0
    path_hit_within_max_rank: bool = False
    smart_strategy: str | None = None
    smart_fallback_used: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_id": self.query_id,
            "query": self.query,
            "top_1_path_hit": self.top_1_path_hit,
            "top_5_path_hit": self.top_5_path_hit,
            "top_1_keyword_hit": self.top_1_keyword_hit,
            "top_5_keyword_hit": self.top_5_keyword_hit,
            "retrieved_path": self.retrieved_path,
            "retrieved_score": self.retrieved_score,
            "latency_ms": self.latency_ms,
            "keywords_found": self.keywords_found,
            "keywords_missing": self.keywords_missing,
            "path_first_hit_rank": self.path_first_hit_rank,
            "path_reciprocal_rank": self.path_reciprocal_rank,
            "path_hit_within_max_rank": self.path_hit_within_max_rank,
            "smart_strategy": self.smart_strategy,
            "smart_fallback_used": self.smart_fallback_used,
        }


@dataclass
class CategoryMetrics:
    """Metrics for a specific category."""

    category: str
    query_count: int
    top_1_path_hits: int
    top_5_path_hits: int
    top_1_keyword_hits: int
    top_5_keyword_hits: int
    avg_latency_ms: float

    @property
    def top_1_path_accuracy(self) -> float:
        return self.top_1_path_hits / self.query_count if self.query_count > 0 else 0.0

    @property
    def top_5_path_accuracy(self) -> float:
        return self.top_5_path_hits / self.query_count if self.query_count > 0 else 0.0

    @property
    def top_1_keyword_accuracy(self) -> float:
        return (
            self.top_1_keyword_hits / self.query_count if self.query_count > 0 else 0.0
        )

    @property
    def top_5_keyword_accuracy(self) -> float:
        return (
            self.top_5_keyword_hits / self.query_count if self.query_count > 0 else 0.0
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "query_count": self.query_count,
            "top_1_path_hits": self.top_1_path_hits,
            "top_5_path_hits": self.top_5_path_hits,
            "top_1_keyword_hits": self.top_1_keyword_hits,
            "top_5_keyword_hits": self.top_5_keyword_hits,
            "top_1_path_accuracy": self.top_1_path_accuracy,
            "top_5_path_accuracy": self.top_5_path_accuracy,
            "top_1_keyword_accuracy": self.top_1_keyword_accuracy,
            "top_5_keyword_accuracy": self.top_5_keyword_accuracy,
            "avg_latency_ms": self.avg_latency_ms,
        }


@dataclass
class FileTypeMetrics:
    """Metrics for a specific file type."""

    file_type: str
    query_count: int
    top_1_path_hits: int
    top_5_path_hits: int
    avg_latency_ms: float

    @property
    def top_1_accuracy(self) -> float:
        return self.top_1_path_hits / self.query_count if self.query_count > 0 else 0.0

    @property
    def top_5_accuracy(self) -> float:
        return self.top_5_path_hits / self.query_count if self.query_count > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_type": self.file_type,
            "query_count": self.query_count,
            "top_1_path_hits": self.top_1_path_hits,
            "top_5_path_hits": self.top_5_path_hits,
            "top_1_accuracy": self.top_1_accuracy,
            "top_5_accuracy": self.top_5_accuracy,
            "avg_latency_ms": self.avg_latency_ms,
        }


@dataclass
class QueryRegression:
    """A single query that regressed between runs."""

    query_id: str
    query: str
    baseline_passed: bool
    current_passed: bool
    baseline_path: str
    current_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_id": self.query_id,
            "query": self.query,
            "baseline_passed": self.baseline_passed,
            "current_passed": self.current_passed,
            "baseline_path": self.baseline_path,
            "current_path": self.current_path,
        }


@dataclass
class RegressionReport:
    """Report comparing current run against baseline."""

    baseline_timestamp: str
    current_timestamp: str
    baseline_top_1: float
    current_top_1: float
    baseline_top_5: float
    current_top_5: float
    baseline_latency_p95: float
    current_latency_p95: float
    top_1_delta: float
    top_5_delta: float
    latency_delta_pct: float
    has_regression: bool
    regressed_queries: list[QueryRegression] = field(default_factory=list)
    improved_queries: list[QueryRegression] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_timestamp": self.baseline_timestamp,
            "current_timestamp": self.current_timestamp,
            "baseline_top_1": self.baseline_top_1,
            "current_top_1": self.current_top_1,
            "baseline_top_5": self.baseline_top_5,
            "current_top_5": self.current_top_5,
            "baseline_latency_p95": self.baseline_latency_p95,
            "current_latency_p95": self.current_latency_p95,
            "top_1_delta": self.top_1_delta,
            "top_5_delta": self.top_5_delta,
            "latency_delta_pct": self.latency_delta_pct,
            "has_regression": self.has_regression,
            "regressed_queries": [q.to_dict() for q in self.regressed_queries],
            "improved_queries": [q.to_dict() for q in self.improved_queries],
        }


@dataclass
class EvaluationReport:
    """Complete evaluation report."""

    timestamp: str
    search_mode: str
    embedding_model: str
    total_queries: int
    quick_set_only: bool

    # Overall metrics
    top_1_path_accuracy: float
    top_5_path_accuracy: float
    top_1_keyword_accuracy: float
    top_5_keyword_accuracy: float

    # Latency metrics
    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    latency_mean_ms: float

    # Breakdown by category and file type
    by_category: dict[str, CategoryMetrics]
    by_file_type: dict[str, FileTypeMetrics]

    # Individual results
    results: list[QueryResult]

    # Optional regression report
    regression: RegressionReport | None = None

    mean_reciprocal_rank: float = 0.0
    within_max_rank_path_accuracy: float = 0.0
    include_stress: bool = False
    stress_only: bool = False
    strict_keywords: bool = False
    strict_keywords_top1: bool = False
    smart_fallback_rate: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "search_mode": self.search_mode,
            "embedding_model": self.embedding_model,
            "total_queries": self.total_queries,
            "quick_set_only": self.quick_set_only,
            "top_1_path_accuracy": self.top_1_path_accuracy,
            "top_5_path_accuracy": self.top_5_path_accuracy,
            "top_1_keyword_accuracy": self.top_1_keyword_accuracy,
            "top_5_keyword_accuracy": self.top_5_keyword_accuracy,
            "mean_reciprocal_rank": self.mean_reciprocal_rank,
            "within_max_rank_path_accuracy": self.within_max_rank_path_accuracy,
            "latency_p50_ms": self.latency_p50_ms,
            "latency_p95_ms": self.latency_p95_ms,
            "latency_p99_ms": self.latency_p99_ms,
            "latency_mean_ms": self.latency_mean_ms,
            "by_category": {k: v.to_dict() for k, v in self.by_category.items()},
            "by_file_type": {k: v.to_dict() for k, v in self.by_file_type.items()},
            "results": [r.to_dict() for r in self.results],
            "regression": self.regression.to_dict() if self.regression else None,
            "include_stress": self.include_stress,
            "stress_only": self.stress_only,
            "strict_keywords": self.strict_keywords,
            "strict_keywords_top1": self.strict_keywords_top1,
            "smart_fallback_rate": self.smart_fallback_rate,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvaluationReport:
        """Create EvaluationReport from dictionary (for loading baselines)."""
        by_category = {}
        for cat_name, cat_data in data.get("by_category", {}).items():
            query_count = cat_data.get("query_count", 0)
            by_category[cat_name] = CategoryMetrics(
                category=cat_data["category"],
                query_count=query_count,
                # Read raw hit counts directly; fall back to computed values for old data
                top_1_path_hits=cat_data.get(
                    "top_1_path_hits",
                    round(cat_data.get("top_1_path_accuracy", 0) * query_count),
                ),
                top_5_path_hits=cat_data.get(
                    "top_5_path_hits",
                    round(cat_data.get("top_5_path_accuracy", 0) * query_count),
                ),
                top_1_keyword_hits=cat_data.get(
                    "top_1_keyword_hits",
                    round(cat_data.get("top_1_keyword_accuracy", 0) * query_count),
                ),
                top_5_keyword_hits=cat_data.get(
                    "top_5_keyword_hits",
                    round(cat_data.get("top_5_keyword_accuracy", 0) * query_count),
                ),
                avg_latency_ms=cat_data.get("avg_latency_ms", 0.0),
            )

        by_file_type = {}
        for ft_name, ft_data in data.get("by_file_type", {}).items():
            query_count = ft_data.get("query_count", 0)
            by_file_type[ft_name] = FileTypeMetrics(
                file_type=ft_data["file_type"],
                query_count=query_count,
                # Read raw hit counts directly; fall back to computed values for old data
                top_1_path_hits=ft_data.get(
                    "top_1_path_hits",
                    round(ft_data.get("top_1_accuracy", 0) * query_count),
                ),
                top_5_path_hits=ft_data.get(
                    "top_5_path_hits",
                    round(ft_data.get("top_5_accuracy", 0) * query_count),
                ),
                avg_latency_ms=ft_data.get("avg_latency_ms", 0.0),
            )

        results = []
        for r in data.get("results", []):
            results.append(
                QueryResult(
                    query_id=r["query_id"],
                    query=r["query"],
                    top_1_path_hit=r["top_1_path_hit"],
                    top_5_path_hit=r["top_5_path_hit"],
                    top_1_keyword_hit=r["top_1_keyword_hit"],
                    top_5_keyword_hit=r["top_5_keyword_hit"],
                    retrieved_path=r["retrieved_path"],
                    retrieved_score=r["retrieved_score"],
                    latency_ms=r["latency_ms"],
                    keywords_found=r.get("keywords_found", []),
                    keywords_missing=r.get("keywords_missing", []),
                    path_first_hit_rank=r.get("path_first_hit_rank"),
                    path_reciprocal_rank=r.get("path_reciprocal_rank", 0.0),
                    path_hit_within_max_rank=r.get("path_hit_within_max_rank", False),
                )
            )

        return cls(
            timestamp=data["timestamp"],
            search_mode=data["search_mode"],
            embedding_model=data.get("embedding_model", "unknown"),
            total_queries=data["total_queries"],
            quick_set_only=data.get("quick_set_only", False),
            top_1_path_accuracy=data["top_1_path_accuracy"],
            top_5_path_accuracy=data["top_5_path_accuracy"],
            top_1_keyword_accuracy=data.get("top_1_keyword_accuracy", 0.0),
            top_5_keyword_accuracy=data.get("top_5_keyword_accuracy", 0.0),
            mean_reciprocal_rank=data.get("mean_reciprocal_rank", 0.0),
            within_max_rank_path_accuracy=data.get("within_max_rank_path_accuracy", 0.0),
            latency_p50_ms=data.get("latency_p50_ms", 0.0),
            latency_p95_ms=data.get("latency_p95_ms", 0.0),
            latency_p99_ms=data.get("latency_p99_ms", 0.0),
            latency_mean_ms=data.get("latency_mean_ms", 0.0),
            by_category=by_category,
            by_file_type=by_file_type,
            results=results,
            regression=None,
            include_stress=data.get("include_stress", False),
            stress_only=data.get("stress_only", False),
            strict_keywords=data.get("strict_keywords", False),
            strict_keywords_top1=data.get("strict_keywords_top1", False),
        )
