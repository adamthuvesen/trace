"""Validated inputs and reports for the evaluation suite."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
import statistics
from typing import Annotated, Literal, Self

from tools.eval.metrics import percentile

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Nonempty = Annotated[str, Field(min_length=1)]
PositiveInt = Annotated[int, Field(strict=True, gt=0)]
Count = Annotated[int, Field(strict=True, ge=0)]
Rate = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Milliseconds = Annotated[float, Field(ge=0, allow_inf_nan=False)]
SearchMode = Literal["semantic", "bm25", "hybrid", "adaptive"]
RecipeValue = str | int | float
METRIC_VERSION = "path-keyword-v1-inclusive-linear-percentiles"
DEFAULT_MIN_KEYWORDS = 2
LATENCY_PROTOCOL = "warm-model-cold-query-cache-core-search-v1"


class EvalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    def to_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")


class GoldenQuery(EvalModel):
    """A golden query with an expected answer location."""

    id: Nonempty
    query: Nonempty
    category: Nonempty
    expected_path: Nonempty
    expected_keywords: list[Nonempty] = Field(default_factory=list)
    file_type: Nonempty = ".md"
    alternate_paths: list[Nonempty] = Field(default_factory=list)
    quick_set: bool = False
    description: str = ""
    difficulty: str = "easy"
    stress_set: bool = False
    min_keywords: Count | None = None
    max_rank: PositiveInt | None = None

    @field_validator("id", "query", "category", "expected_path")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be blank")
        return value

    @field_validator("expected_keywords", mode="before")
    @classmethod
    def numeric_keywords(cls, value: object) -> object:
        # Shipped YAML fixtures contain numeric HTTP status keywords.
        if isinstance(value, list):
            return [str(item) if type(item) in (int, float) else item for item in value]
        return value

    @field_validator("expected_path", "alternate_paths")
    @classmethod
    def relative_paths(cls, value: str | list[str]) -> str | list[str]:
        for item in [value] if isinstance(value, str) else value:
            if PurePosixPath(item).is_absolute() or ".." in PurePosixPath(item).parts:
                raise ValueError(
                    "expected paths must be relative to the knowledge base"
                )
        return value

    @model_validator(mode="after")
    def keyword_requirement(self) -> Self:
        if self.min_keywords is not None and self.min_keywords > len(
            self.expected_keywords
        ):
            raise ValueError("min_keywords exceeds the expected keyword count")
        return self

    @classmethod
    def from_dict(cls, data: object) -> GoldenQuery:
        return cls.model_validate(data)

    def matches_path(self, retrieved_path: str) -> bool:
        normalized = Path(retrieved_path).as_posix().lower()
        return any(
            normalized == Path(path).as_posix().lower()
            for path in [self.expected_path, *self.alternate_paths]
        )


class GoldenQueries(EvalModel):
    version: Literal["1.0"] = "1.0"
    description: str = ""
    queries: list[GoldenQuery] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        ids = [query.id for query in self.queries]
        if len(ids) != len(set(ids)):
            raise ValueError("golden query IDs must be unique")
        return self


class EvaluationScope(EvalModel):
    quick_only: bool = False
    categories: list[str] = Field(default_factory=list)
    file_types: list[str] = Field(default_factory=list)
    stress_only: bool = False
    include_stress: bool = False


class EvaluationManifest(EvalModel):
    corpus_fingerprint: Nonempty
    queryset_fingerprint: Nonempty
    selected_query_ids: list[Nonempty] = Field(min_length=1)
    scope: EvaluationScope
    metric_version: Nonempty = METRIC_VERSION
    search_mode: SearchMode
    top_k: PositiveInt = 5
    min_keywords: Count = DEFAULT_MIN_KEYWORDS
    strict_keywords: bool = False
    strict_keywords_top1: bool = False
    latency_protocol: Nonempty = LATENCY_PROTOCOL
    build_recipe: dict[str, RecipeValue]
    source_revision: Nonempty
    source_fingerprint: Nonempty
    latency_environment: Nonempty
    provenance_note: str = ""
    includes_stress_queries: bool = False

    @field_validator("build_recipe")
    @classmethod
    def model_identity(cls, value: dict[str, RecipeValue]) -> dict[str, RecipeValue]:
        model = value.get("embedding_model")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("build_recipe requires an embedding_model identity")
        return value

    @model_validator(mode="after")
    def unique_query_ids(self) -> Self:
        if len(self.selected_query_ids) != len(set(self.selected_query_ids)):
            raise ValueError("manifest query IDs must be unique")
        return self


class QueryResult(EvalModel):
    query_id: Nonempty
    query: str
    top_1_path_hit: bool
    top_5_path_hit: bool
    top_1_keyword_hit: bool
    top_5_keyword_hit: bool
    retrieved_path: str
    retrieved_score: float
    latency_ms: Milliseconds
    keywords_found: list[str] = Field(default_factory=list)
    keywords_missing: list[str] = Field(default_factory=list)
    path_first_hit_rank: PositiveInt | None = None
    path_reciprocal_rank: Rate = 0.0
    path_hit_within_max_rank: bool = False
    adaptive_strategy: str | None = None
    adaptive_fallback_used: bool | None = None
    category: str = ""
    file_type: str = ".md"


class CategoryMetrics(EvalModel):
    category: str
    query_count: Count
    top_1_path_hits: Count
    top_5_path_hits: Count
    top_1_keyword_hits: Count
    top_5_keyword_hits: Count
    avg_latency_ms: Milliseconds

    @model_validator(mode="after")
    def bounded_hits(self) -> Self:
        if any(
            count > self.query_count
            for count in (
                self.top_1_path_hits,
                self.top_5_path_hits,
                self.top_1_keyword_hits,
                self.top_5_keyword_hits,
            )
        ):
            raise ValueError("hit counts must not exceed query_count")
        return self

    @property
    def top_1_path_accuracy(self) -> float:
        return self.top_1_path_hits / self.query_count if self.query_count else 0.0

    @property
    def top_5_path_accuracy(self) -> float:
        return self.top_5_path_hits / self.query_count if self.query_count else 0.0

    @property
    def top_1_keyword_accuracy(self) -> float:
        return self.top_1_keyword_hits / self.query_count if self.query_count else 0.0

    @property
    def top_5_keyword_accuracy(self) -> float:
        return self.top_5_keyword_hits / self.query_count if self.query_count else 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            **super().to_dict(),
            **{
                name: getattr(self, name)
                for name in (
                    "top_1_path_accuracy",
                    "top_5_path_accuracy",
                    "top_1_keyword_accuracy",
                    "top_5_keyword_accuracy",
                )
            },
        }


class FileTypeMetrics(EvalModel):
    file_type: str
    query_count: Count
    top_1_path_hits: Count
    top_5_path_hits: Count
    avg_latency_ms: Milliseconds

    @model_validator(mode="after")
    def bounded_hits(self) -> Self:
        if max(self.top_1_path_hits, self.top_5_path_hits) > self.query_count:
            raise ValueError("hit counts must not exceed query_count")
        return self

    @property
    def top_1_accuracy(self) -> float:
        return self.top_1_path_hits / self.query_count if self.query_count else 0.0

    @property
    def top_5_accuracy(self) -> float:
        return self.top_5_path_hits / self.query_count if self.query_count else 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            **super().to_dict(),
            "top_1_accuracy": self.top_1_accuracy,
            "top_5_accuracy": self.top_5_accuracy,
        }


class QueryRegression(EvalModel):
    query_id: str
    query: str
    baseline_passed: bool
    current_passed: bool
    baseline_path: str
    current_path: str


class RegressionReport(EvalModel):
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
    regressed_queries: list[QueryRegression] = Field(default_factory=list)
    improved_queries: list[QueryRegression] = Field(default_factory=list)
    experiment_differences: list[str] = Field(default_factory=list)
    latency_compared: bool = True


class EvaluationMetrics(EvalModel):
    top_1_path_accuracy: Rate
    top_5_path_accuracy: Rate
    top_1_keyword_accuracy: Rate = 0.0
    top_5_keyword_accuracy: Rate = 0.0
    latency_p50_ms: Milliseconds = 0.0
    latency_p95_ms: Milliseconds = 0.0
    latency_p99_ms: Milliseconds = 0.0
    latency_mean_ms: Milliseconds = 0.0
    mean_reciprocal_rank: Rate = 0.0
    within_max_rank_path_accuracy: Rate = 0.0
    adaptive_fallback_rate: Rate | None = None

    @classmethod
    def summarize(
        cls, results: list[QueryResult], *, adaptive: bool
    ) -> EvaluationMetrics:
        total = len(results)
        if not total:
            raise ValueError("current reports require a nonempty result population")
        latencies = sorted(result.latency_ms for result in results)
        flags = [
            result.adaptive_fallback_used
            for result in results
            if result.adaptive_fallback_used is not None
        ]
        return cls(
            top_1_path_accuracy=sum(result.top_1_path_hit for result in results)
            / total,
            top_5_path_accuracy=sum(result.top_5_path_hit for result in results)
            / total,
            top_1_keyword_accuracy=sum(result.top_1_keyword_hit for result in results)
            / total,
            top_5_keyword_accuracy=sum(result.top_5_keyword_hit for result in results)
            / total,
            mean_reciprocal_rank=statistics.mean(
                result.path_reciprocal_rank for result in results
            ),
            within_max_rank_path_accuracy=sum(
                result.path_hit_within_max_rank for result in results
            )
            / total,
            latency_p50_ms=percentile(latencies, 50),
            latency_p95_ms=percentile(latencies, 95),
            latency_p99_ms=percentile(latencies, 99),
            latency_mean_ms=statistics.mean(latencies),
            adaptive_fallback_rate=sum(bool(flag) for flag in flags) / len(flags)
            if adaptive and flags
            else None,
        )


def category_metrics(results: list[QueryResult]) -> dict[str, CategoryMetrics]:
    grouped: dict[str, list[QueryResult]] = {}
    for result in results:
        grouped.setdefault(result.category, []).append(result)
    return {
        category: CategoryMetrics(
            category=category,
            query_count=len(items),
            top_1_path_hits=sum(item.top_1_path_hit for item in items),
            top_5_path_hits=sum(item.top_5_path_hit for item in items),
            top_1_keyword_hits=sum(item.top_1_keyword_hit for item in items),
            top_5_keyword_hits=sum(item.top_5_keyword_hit for item in items),
            avg_latency_ms=statistics.mean(item.latency_ms for item in items),
        )
        for category, items in grouped.items()
    }


def file_type_metrics(results: list[QueryResult]) -> dict[str, FileTypeMetrics]:
    grouped: dict[str, list[QueryResult]] = {}
    for result in results:
        grouped.setdefault(result.file_type, []).append(result)
    return {
        file_type: FileTypeMetrics(
            file_type=file_type,
            query_count=len(items),
            top_1_path_hits=sum(item.top_1_path_hit for item in items),
            top_5_path_hits=sum(item.top_5_path_hit for item in items),
            avg_latency_ms=statistics.mean(item.latency_ms for item in items),
        )
        for file_type, items in grouped.items()
    }


class EvaluationReport(EvaluationMetrics):
    timestamp: str
    search_mode: SearchMode | Literal["reranked"]
    embedding_model: str = "unknown"
    total_queries: Count
    quick_set_only: bool = False
    by_category: dict[str, CategoryMetrics] = Field(default_factory=dict)
    by_file_type: dict[str, FileTypeMetrics] = Field(default_factory=dict)
    results: list[QueryResult] = Field(default_factory=list)
    regression: RegressionReport | None = None
    include_stress: bool = False
    stress_only: bool = False
    strict_keywords: bool = False
    strict_keywords_top1: bool = False
    manifest: EvaluationManifest | None = None

    @classmethod
    def from_results(
        cls, *, timestamp: str, manifest: EvaluationManifest, results: list[QueryResult]
    ) -> EvaluationReport:
        metrics = EvaluationMetrics.summarize(
            results, adaptive=manifest.search_mode == "adaptive"
        )
        return cls.model_validate(
            {
                **metrics.to_dict(),
                "timestamp": timestamp,
                "manifest": manifest,
                "results": results,
                "search_mode": manifest.search_mode,
                "embedding_model": manifest.build_recipe["embedding_model"],
                "total_queries": len(results),
                "quick_set_only": manifest.scope.quick_only,
                "include_stress": manifest.includes_stress_queries,
                "stress_only": manifest.scope.stress_only,
                "strict_keywords": manifest.strict_keywords,
                "strict_keywords_top1": manifest.strict_keywords_top1,
                "by_category": category_metrics(results),
                "by_file_type": file_type_metrics(results),
            }
        )

    @model_validator(mode="after")
    def result_population(self) -> Self:
        ids = [result.query_id for result in self.results]
        if len(ids) != len(set(ids)):
            raise ValueError("report query IDs must be unique")
        if self.manifest is not None:
            if (
                len(ids) != self.total_queries
                or ids != self.manifest.selected_query_ids
            ):
                raise ValueError(
                    "report results must match the manifest query population"
                )
            if self.search_mode != self.manifest.search_mode:
                raise ValueError("report search mode must match its manifest")
            expected_flags = {
                "embedding_model": self.manifest.build_recipe["embedding_model"],
                "quick_set_only": self.manifest.scope.quick_only,
                "include_stress": self.manifest.includes_stress_queries,
                "stress_only": self.manifest.scope.stress_only,
                "strict_keywords": self.manifest.strict_keywords,
                "strict_keywords_top1": self.manifest.strict_keywords_top1,
            }
            for name, expected in expected_flags.items():
                if getattr(self, name) != expected:
                    raise ValueError(f"report {name} must match its manifest")
            for result in self.results:
                rank = result.path_first_hit_rank
                if rank is not None and rank > self.manifest.top_k:
                    raise ValueError("result path rank exceeds manifest top_k")
                if result.path_reciprocal_rank != (1.0 / rank if rank else 0.0):
                    raise ValueError("result reciprocal rank contradicts its path rank")
                if result.top_1_path_hit != (rank == 1) or result.top_5_path_hit != (
                    rank is not None and rank <= 5
                ):
                    raise ValueError("result path hits contradict their first hit rank")
                if rank is None and result.path_hit_within_max_rank:
                    raise ValueError(
                        "result without a path hit cannot satisfy max_rank"
                    )
                if result.top_1_keyword_hit and not result.top_5_keyword_hit:
                    raise ValueError("result keyword hits contradict their scopes")
                if (
                    self.manifest.strict_keywords_top1
                    and result.top_1_keyword_hit != result.top_5_keyword_hit
                ):
                    raise ValueError(
                        "top-1 keyword scope requires equal keyword metrics"
                    )
            expected_metrics = EvaluationMetrics.summarize(
                self.results, adaptive=self.search_mode == "adaptive"
            )
            for name in EvaluationMetrics.model_fields:
                if getattr(self, name) != getattr(expected_metrics, name):
                    raise ValueError(f"report {name} contradicts its result rows")
            if self.by_category != category_metrics(self.results):
                raise ValueError("by_category contradicts result rows")
            if self.by_file_type != file_type_metrics(self.results):
                raise ValueError("by_file_type contradicts result rows")
        return self

    def to_dict(self) -> dict[str, object]:
        return {
            **super().to_dict(),
            "by_category": {
                key: value.to_dict() for key, value in self.by_category.items()
            },
            "by_file_type": {
                key: value.to_dict() for key, value in self.by_file_type.items()
            },
        }

    @classmethod
    def from_dict(cls, data: object) -> EvaluationReport:
        """Decode shipped count or accuracy-only reports without inventing provenance."""
        if not isinstance(data, dict):
            raise ValueError("evaluation report must be an object")
        decoded = dict(data)
        current_schema = decoded.get("manifest") is not None
        for group, metrics, names in (
            (
                "by_category",
                CategoryMetrics,
                ("top_1_path", "top_5_path", "top_1_keyword", "top_5_keyword"),
            ),
            ("by_file_type", FileTypeMetrics, ("top_1", "top_5")),
        ):
            raw_group = decoded.get(group, {})
            if not isinstance(raw_group, dict):
                raise ValueError(f"{group} must be an object")
            converted: dict[str, object] = {}
            for key, raw in raw_group.items():
                if not isinstance(key, str) or not isinstance(raw, dict):
                    raise ValueError(f"invalid {group} entry")
                item = dict(raw)
                count = item.get("query_count", 0)
                if type(count) is not int:
                    raise ValueError("query_count must be an integer")
                for name in names:
                    accuracy = item.pop(f"{name}_accuracy", 0)
                    hit_name = (
                        f"{name}_hits"
                        if group == "by_category"
                        else f"{name}_path_hits"
                    )
                    if hit_name not in item and not current_schema:
                        if not isinstance(accuracy, (int, float)):
                            raise ValueError("legacy accuracy must be numeric")
                        item[hit_name] = round(accuracy * count)
                converted_metrics = metrics.model_validate(item)
                if current_schema:
                    for name in names:
                        derived_name = f"{name}_accuracy"
                        if derived_name in raw and raw[derived_name] != getattr(
                            converted_metrics, derived_name
                        ):
                            raise ValueError(
                                f"{group} {derived_name} contradicts its hit counts"
                            )
                converted[key] = converted_metrics
            decoded[group] = converted
        return cls.model_validate(decoded)
