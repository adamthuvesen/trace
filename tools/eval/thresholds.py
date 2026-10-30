"""Validated threshold configuration, preserving the shipped thresholds."""

from typing import Annotated, Literal, NotRequired, TypedDict

from pydantic import ConfigDict, Field, TypeAdapter, with_config


@with_config(ConfigDict(extra="forbid", strict=True, allow_inf_nan=False))
class Band(TypedDict):
    target: float
    warning: float
    critical: float


@with_config(ConfigDict(extra="forbid", strict=True, allow_inf_nan=False))
class AccuracyThresholds(TypedDict):
    top_1: Band
    top_5: Band


@with_config(ConfigDict(extra="forbid", strict=True, allow_inf_nan=False))
class LatencyThresholds(TypedDict):
    p50: Band
    p95: Band
    p99: Band


@with_config(ConfigDict(extra="forbid", strict=True, allow_inf_nan=False))
class RegressionThresholds(TypedDict):
    top_1_drop_threshold: float
    top_5_drop_threshold: float
    latency_increase_threshold: float
    min_regressed_queries: Annotated[int, Field(ge=1)]


@with_config(ConfigDict(extra="forbid", strict=True, allow_inf_nan=False))
class KeywordMatch(TypedDict):
    min_keywords: Annotated[int, Field(ge=0)]


@with_config(ConfigDict(extra="forbid", strict=True, allow_inf_nan=False))
class CIThresholds(TypedDict):
    fail_on: list[
        Literal[
            "top_1_below_critical",
            "top_5_below_critical",
            "top_1_keyword_below_critical",
            "top_5_keyword_below_critical",
            "mrr_below_critical",
            "latency_above_critical",
            "regression_detected",
        ]
    ]
    mrr_critical: NotRequired[float]


@with_config(ConfigDict(extra="forbid", strict=True, allow_inf_nan=False))
class StressThresholds(TypedDict):
    path_accuracy: NotRequired[AccuracyThresholds]
    keyword_accuracy: NotRequired[AccuracyThresholds]
    latency: NotRequired[LatencyThresholds]
    ci: NotRequired[CIThresholds]


@with_config(ConfigDict(extra="forbid", strict=True, allow_inf_nan=False))
class AdaptiveThresholds(TypedDict):
    fallback_rate: Band


@with_config(ConfigDict(extra="forbid", strict=True, allow_inf_nan=False))
class Thresholds(TypedDict):
    version: str
    description: str
    path_accuracy: AccuracyThresholds
    keyword_accuracy: AccuracyThresholds
    latency: LatencyThresholds
    regression: RegressionThresholds
    keyword_match: KeywordMatch
    ci: CIThresholds
    stress: NotRequired[StressThresholds]
    adaptive: NotRequired[AdaptiveThresholds]


THRESHOLDS_ADAPTER = TypeAdapter(Thresholds)
