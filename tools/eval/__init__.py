"""Evaluation suite for Trace search."""

from pathlib import Path

import yaml

from tools.eval.models import (
    CategoryMetrics,
    EvaluationReport,
    FileTypeMetrics,
    GoldenQuery,
    QueryResult,
    RegressionReport,
)

EVAL_DIR = Path(__file__).parent
THRESHOLDS_PATH = EVAL_DIR / "thresholds.yaml"


def load_thresholds() -> dict:
    """Load evaluation thresholds from YAML."""
    try:
        with open(THRESHOLDS_PATH) as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in thresholds.yaml: {e}") from e
    except FileNotFoundError:
        raise ValueError(f"Thresholds file not found: {THRESHOLDS_PATH}") from None

    if not isinstance(data, dict):
        raise ValueError("thresholds.yaml must contain a dictionary")

    return data


__all__ = [
    "CategoryMetrics",
    "EvaluationReport",
    "FileTypeMetrics",
    "GoldenQuery",
    "QueryResult",
    "RegressionReport",
    "load_thresholds",
]
