"""Evaluation trust boundaries and comparison compatibility."""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import yaml
from click.testing import CliRunner
from pydantic import ValidationError

from tests.search_hits import make_hit
from trace_search.config import get_settings
from tools.eval.battle_royale import load_suite
from tools.eval.cli import main
from tools.eval.evaluator import (
    evaluate_query,
    get_golden_queries_path,
    load_golden_queries,
    run_evaluation,
)
from tools.eval.models import (
    EvaluationManifest,
    EvaluationReport,
    EvaluationScope,
    GoldenQuery,
    QueryResult,
)
from tools.eval.provenance import fingerprint
from tools.eval.regression import (
    compare_results,
    promote_to_baseline,
    regression_failures,
)

FIXTURE_GOLDEN = Path("tests/fixtures/eval_golden_queries.yaml")


def query_data() -> dict[str, object]:
    return {
        "id": "one",
        "query": "lookup",
        "category": "search",
        "expected_path": "answer.md",
        "expected_keywords": ["one", "two"],
    }


def report() -> EvaluationReport:
    manifest = EvaluationManifest(
        corpus_fingerprint="corpus",
        queryset_fingerprint="queries",
        selected_query_ids=["one"],
        scope=EvaluationScope(),
        search_mode="adaptive",
        build_recipe={"embedding_model": "test"},
        source_revision="revision",
        source_fingerprint="source",
        latency_environment="host",
    )
    result = QueryResult(
        query_id="one",
        query="lookup",
        top_1_path_hit=True,
        top_5_path_hit=True,
        top_1_keyword_hit=True,
        top_5_keyword_hit=True,
        retrieved_path="answer.md",
        retrieved_score=1.0,
        latency_ms=1.0,
        path_first_hit_rank=1,
        path_reciprocal_rank=1.0,
        path_hit_within_max_rank=True,
    )
    return EvaluationReport.from_results(
        timestamp="2026-11-04T00:00:00+00:00", manifest=manifest, results=[result]
    )


@pytest.mark.parametrize(
    "invalid",
    [
        {"max_rank": 0},
        {"max_rank": -1},
        {"max_rank": "1"},
        {"min_keywords": -1},
        {"min_keywords": 3},
        {"quick_set": "false"},
        {"expected_keywords": [True]},
        {"unknown": True},
        {"expected_path": "../private.md"},
        {"query": ""},
    ],
)
def test_invalid_query_fields_fail(invalid):
    with pytest.raises(ValidationError):
        GoldenQuery.from_dict({**query_data(), **invalid})


def test_duplicate_ids_rejected_before_filtering(tmp_path):
    path = tmp_path / "queries.yaml"
    path.write_text(
        yaml.safe_dump(
            {"queries": [query_data(), {**query_data(), "stress_set": True}]}
        )
    )
    with pytest.raises(ValueError, match="unique"):
        load_golden_queries(golden_queries_path=path)


def test_empty_scope_fails_before_index_or_model_access():
    indexer = Mock()
    with pytest.raises(ValueError, match="No queries"):
        run_evaluation(
            indexer, golden_queries_path=FIXTURE_GOLDEN, categories=["absent"]
        )
    assert indexer.mock_calls == []


def test_invalid_top_k_fails_before_index_access():
    indexer = Mock()
    with pytest.raises(ValueError, match="top_k"):
        run_evaluation(indexer, golden_queries_path=FIXTURE_GOLDEN, top_k=0)
    assert indexer.mock_calls == []


def test_invalid_settings_do_not_fall_back_to_query_file(monkeypatch):
    monkeypatch.delenv("EVAL_GOLDEN_QUERIES", raising=False)
    with patch(
        "trace_search.config.get_settings", side_effect=ValueError("bad settings")
    ):
        with pytest.raises(ValueError, match="bad settings"):
            get_golden_queries_path()


@pytest.mark.parametrize(
    "field,value",
    [
        ("corpus_fingerprint", "changed"),
        ("queryset_fingerprint", "changed"),
        ("top_k", 10),
        ("metric_version", "new"),
        ("strict_keywords", True),
        ("latency_protocol", "cold"),
        ("scope", EvaluationScope(quick_only=True)),
    ],
)
def test_comparison_rejects_changed_inputs(field, value):
    current, baseline = report(), report()
    setattr(current.manifest, field, value)
    current = EvaluationReport.from_results(
        timestamp=current.timestamp, manifest=current.manifest, results=current.results
    )
    with pytest.raises(ValueError, match=field):
        compare_results(current, baseline)


def test_comparison_records_deliberate_experiment_changes():
    current, baseline = report(), report()
    current.manifest.build_recipe = {"embedding_model": "other"}
    current.manifest.source_revision = "new"
    current = EvaluationReport.from_results(
        timestamp=current.timestamp, manifest=current.manifest, results=current.results
    )
    compared = compare_results(current, baseline)
    assert compared.experiment_differences == ["build_recipe", "source_revision"]
    assert not compared.has_regression


def test_cross_host_latency_requires_quality_only():
    current, baseline = report(), report()
    current.manifest.latency_environment = "different-host"
    current.results[0].latency_ms = 100.0
    current = EvaluationReport.from_results(
        timestamp=current.timestamp, manifest=current.manifest, results=current.results
    )
    with pytest.raises(ValueError, match="quality-only"):
        compare_results(current, baseline)
    compared = compare_results(current, baseline, compare_latency=False)
    assert not compared.latency_compared
    assert not compared.has_regression
    assert compared.latency_delta_pct == 99.0


def test_legacy_reports_read_but_do_not_compare():
    data = report().to_dict()
    data.pop("manifest")
    data["by_category"] = {
        "search": {
            "category": "search",
            "query_count": 1,
            "top_1_path_accuracy": 1.0,
            "top_5_path_accuracy": 1.0,
            "top_1_keyword_accuracy": 0.0,
            "top_5_keyword_accuracy": 0.0,
            "avg_latency_ms": 1.0,
        }
    }
    legacy = EvaluationReport.from_dict(data)
    assert legacy.by_category["search"].top_1_path_hits == 1
    with pytest.raises(ValueError, match="legacy reports without provenance"):
        compare_results(report(), legacy)


def test_duplicate_report_results_cannot_silently_overwrite():
    current = report()
    current.results.append(current.results[0])
    with pytest.raises(ValueError, match="unique"):
        compare_results(current, report())


def test_failed_evaluation_cannot_replace_baseline(tmp_path):
    target = tmp_path / "baseline.json"
    target.write_text("unchanged")
    failed = report()
    failed.results[0].top_1_path_hit = False
    failed.results[0].path_first_hit_rank = 2
    failed.results[0].path_reciprocal_rank = 0.5
    failed = EvaluationReport.from_results(
        timestamp=failed.timestamp, manifest=failed.manifest, results=failed.results
    )
    failed.regression = compare_results(failed, report())
    with pytest.raises(ValueError, match="Cannot promote failed"):
        promote_to_baseline(failed, output_path=target)
    assert target.read_text() == "unchanged"


def test_ci_gate_requires_a_baseline_comparison():
    with pytest.raises(ValueError, match="baseline comparison"):
        regression_failures(report())


def test_ci_gate_fails_on_regression_and_passes_a_match():
    current = report()
    current.regression = compare_results(current, report())
    assert regression_failures(current) == []
    current.results[0].top_1_path_hit = False
    current.results[0].path_first_hit_rank = 2
    current.results[0].path_reciprocal_rank = 0.5
    worse = EvaluationReport.from_results(
        timestamp=current.timestamp, manifest=current.manifest, results=current.results
    )
    worse.regression = compare_results(worse, report())
    assert regression_failures(worse)[0].startswith("Regression against baseline")


def test_report_roundtrip_preserves_regression_and_manifest():
    current = report()
    current.regression = compare_results(current, report())
    assert (
        EvaluationReport.from_dict(json.loads(json.dumps(current.to_dict()))) == current
    )


def test_suite_rejects_duplicate_ids(tmp_path):
    path = tmp_path / "suite.yaml"
    item = {"id": "same", "kb_path": ".", "golden_queries": "queries.yaml"}
    path.write_text(yaml.safe_dump({"knowledge_bases": [item, item]}))
    with pytest.raises(Exception, match="unique"):
        load_suite(path)


def test_ci_missing_comparison_baseline_fails_before_index(monkeypatch, tmp_path):
    monkeypatch.setenv("EVAL_GOLDEN_QUERIES", str(FIXTURE_GOLDEN.resolve()))
    get_settings.cache_clear()
    with (
        patch("tools.eval.cli.get_latest_baseline", return_value=None),
        patch("trace_search.indexing.wiki_indexer.WikiIndexer") as indexer,
    ):
        result = CliRunner().invoke(
            main, ["--ci", "--full", "--output-dir", str(tmp_path)]
        )
    assert result.exit_code == 1
    assert "requires a comparative baseline" in result.output
    indexer.assert_not_called()
    get_settings.cache_clear()


def test_cli_always_uses_scratch_index(monkeypatch, tmp_path):
    monkeypatch.setenv("EVAL_GOLDEN_QUERIES", str(FIXTURE_GOLDEN.resolve()))
    monkeypatch.setenv("KB_PATH", str(Path("tests/fixtures/eval_kb").resolve()))
    configured_index = tmp_path / "served-index"
    monkeypatch.setenv("INDEX_PATH", str(configured_index))
    get_settings.cache_clear()
    with (
        patch("trace_search.indexing.wiki_indexer.WikiIndexer") as indexer,
        patch("tools.eval.cli.run_evaluation", return_value=report()),
    ):
        result = CliRunner().invoke(
            main, ["--full", "--output-dir", str(tmp_path / "reports")]
        )
    assert result.exit_code == 0, result.output
    scratch = indexer.call_args.kwargs["index_root"]
    assert scratch != configured_index
    assert not scratch.exists()
    assert not configured_index.exists()
    indexer.return_value.build_index.assert_called_once_with(force=True)
    get_settings.cache_clear()


def test_shipped_top5_path_and_keyword_scope_semantics():
    query = GoldenQuery.from_dict(query_data())
    hits = [make_hit("other.md", score=1.0) for _ in range(5)]
    hits.append(make_hit("answer.md", content="one two", score=1.0))
    searcher = Mock()
    searcher.search.return_value = hits
    result = evaluate_query(query, searcher, "semantic", top_k=10)
    assert not result.top_5_path_hit
    assert result.top_5_keyword_hit
    assert result.path_first_hit_rank == 6
    assert result.path_reciprocal_rank == pytest.approx(1 / 6)


def test_queryset_fingerprint_contains_no_absolute_path_or_mtime():
    queries = load_golden_queries(golden_queries_path=FIXTURE_GOLDEN)
    assert fingerprint([query.to_dict() for query in queries]) == fingerprint(
        [
            query.to_dict()
            for query in load_golden_queries(
                golden_queries_path=FIXTURE_GOLDEN.resolve()
            )
        ]
    )


def test_committed_benchmark_artifacts_contain_no_absolute_home_paths():
    home_path = re.compile(r"/(?:Users|home)/[^/\s\"]+")
    leaks = [
        f"{path}: {match.group()}"
        for root in (Path("docs/benchmarks"), Path("tools/eval/baselines"))
        for path in sorted(root.rglob("*"))
        if path.is_file()
        for match in [home_path.search(path.read_text(errors="replace"))]
        if match
    ]
    assert not leaks, (
        "Committed benchmark artifacts name a local home path. "
        "Rerun the evaluation against a public fixture or replace the path "
        f"with a repository-relative one: {leaks}"
    )


def test_shipped_historical_reports_remain_readable():
    paths = []
    for path in Path("docs/benchmarks").rglob("*.json"):
        data = json.loads(path.read_text())
        if isinstance(data, dict) and "search_mode" in data and "total_queries" in data:
            paths.append(path)
            decoded = EvaluationReport.from_dict(data)
            assert decoded.search_mode == data["search_mode"]
            assert decoded.manifest is None
    assert paths


@pytest.mark.parametrize(
    "field,value",
    [
        ("top_1_path_accuracy", 0.0),
        ("top_5_path_accuracy", 0.0),
        ("latency_p95_ms", 0.01),
        ("mean_reciprocal_rank", 0.0),
        ("strict_keywords", True),
        ("stress_only", True),
        ("embedding_model", "invented"),
    ],
)
def test_current_report_rejects_conflicting_aggregates_and_flags(
    field, value, tmp_path
):
    current = report()
    setattr(current, field, value)
    with pytest.raises(ValueError, match=field):
        regression_failures(current)
    with pytest.raises(ValueError, match=field):
        compare_results(current, report())
    with pytest.raises(ValueError, match=field):
        promote_to_baseline(current, tmp_path / "baseline.json")
    assert not (tmp_path / "baseline.json").exists()


def test_false_green_result_rows_cannot_pass_gate_or_promotion(tmp_path):
    current = report()
    current.results[0].top_1_path_hit = False
    current.results[0].top_5_path_hit = False
    current.results[0].latency_ms = 99999.0
    for operation in (
        lambda: regression_failures(current),
        lambda: compare_results(current, report()),
        lambda: promote_to_baseline(current, tmp_path / "baseline.json"),
    ):
        with pytest.raises(ValueError, match="contradict"):
            operation()
    assert not (tmp_path / "baseline.json").exists()


def test_current_group_metrics_require_counts_and_reject_conflicting_accuracy():
    current = report().to_dict()
    current["by_category"] = {
        "": {"category": "", "query_count": 1, "avg_latency_ms": 1.0}
    }
    with pytest.raises(ValueError, match="top_1_path_hits"):
        EvaluationReport.from_dict(current)
    current = report().to_dict()
    current["by_category"][""]["top_1_path_accuracy"] = 0.0
    with pytest.raises(ValueError, match="contradicts its hit counts"):
        EvaluationReport.from_dict(current)


@pytest.mark.parametrize(
    "invalid",
    [
        {"path_first_hit_rank": 6, "path_reciprocal_rank": 1 / 6},
        {"path_reciprocal_rank": 0.5},
        {"top_1_path_hit": False},
    ],
)
def test_current_result_rank_must_match_metrics_and_retrieval_scope(invalid):
    current = report()
    for name, value in invalid.items():
        setattr(current.results[0], name, value)
    with pytest.raises(ValueError, match="rank"):
        EvaluationReport.from_results(
            timestamp=current.timestamp,
            manifest=current.manifest,
            results=current.results,
        )


def test_manifest_requires_model_identity():
    data = report().manifest.to_dict()
    data["build_recipe"] = {}
    with pytest.raises(ValueError, match="embedding_model identity"):
        EvaluationManifest.model_validate(data)
