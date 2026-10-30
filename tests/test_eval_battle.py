"""Comparative battle gates and model-free baseline preflight."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from tools.eval.battle_royale import main
from tools.eval.models import EvaluationReport
from tools.eval.regression import load_baseline

BASELINES = Path("tools/eval/baselines/battle-standard")
CHALLENGE_BASELINES = Path("tools/eval/baselines/battle-challenge")


def collapsed_report(reference: EvaluationReport) -> EvaluationReport:
    results = [
        result.model_copy(
            update={
                "top_1_path_hit": False,
                "top_5_path_hit": False,
                "top_1_keyword_hit": False,
                "top_5_keyword_hit": False,
                "path_first_hit_rank": None,
                "path_reciprocal_rank": 0.0,
                "path_hit_within_max_rank": False,
                "retrieved_path": "(no results)",
            }
        )
        for result in reference.results
    ]
    return EvaluationReport.from_results(
        timestamp=reference.timestamp, manifest=reference.manifest, results=results
    )


def test_collapsed_battle_fails_and_retains_reports(tmp_path):
    references = {
        name: load_baseline(BASELINES / f"{name}_bm25.json")
        for name in ("retrieval", "support", "api")
    }
    collapsed = collapsed_report(references["retrieval"])
    with (
        patch("trace_search.indexing.embeddings.build_embedding_backend"),
        patch("trace_search.indexing.wiki_indexer.WikiIndexer"),
        patch(
            "tools.eval.battle_royale.run_evaluation",
            side_effect=[collapsed, references["support"], references["api"]],
        ),
    ):
        result = CliRunner().invoke(
            main,
            [
                "--mode",
                "bm25",
                "--baseline-dir",
                str(BASELINES),
                "--quality-only",
                "--output-dir",
                str(tmp_path),
                "--label",
                "collapsed",
            ],
        )
    assert result.exit_code == 1, result.output
    assert "retrieval/bm25: regression" in result.output
    assert "retrieval/bm25 query easy-bm25: lost Top-1, Top-5" in result.output
    run_dir = tmp_path / "collapsed"
    stored = load_baseline(run_dir / "retrieval_bm25.json")
    assert stored.regression.has_regression
    assert stored.top_1_path_accuracy == 0.0
    assert (run_dir / "api_bm25.json").is_file()
    summary = json.loads((run_dir / "summary.json").read_text())
    assert summary["comparison_failures"]
    assert summary["comparisons"]["retrieval"]["bm25"]["has_regression"]
    assert "## Comparative gate\n\nFAIL" in (run_dir / "summary.md").read_text()


def test_matching_battle_passes_existing_comparison_thresholds(tmp_path):
    references = [
        load_baseline(BASELINES / f"{name}_bm25.json") for name in ("retrieval", "support", "api")
    ]
    with (
        patch("trace_search.indexing.embeddings.build_embedding_backend"),
        patch("trace_search.indexing.wiki_indexer.WikiIndexer"),
        patch("tools.eval.battle_royale.run_evaluation", side_effect=references),
    ):
        result = CliRunner().invoke(
            main,
            [
                "--mode",
                "bm25",
                "--baseline-dir",
                str(BASELINES),
                "--quality-only",
                "--output-dir",
                str(tmp_path),
                "--label",
                "matching",
            ],
        )
    assert result.exit_code == 0, result.output
    assert "all KB/mode gates passed" in result.output
    summary = json.loads((tmp_path / "matching/summary.json").read_text())
    assert summary["comparison_failures"] == []
    assert not any(
        comparison["has_regression"]
        for by_mode in summary["comparisons"].values()
        for comparison in by_mode.values()
    )


def test_missing_requested_baseline_fails_before_model_or_index(tmp_path):
    baseline_dir = tmp_path / "baselines"
    shutil.copytree(BASELINES, baseline_dir)
    (baseline_dir / "api_bm25.json").unlink()
    with (
        patch("trace_search.indexing.embeddings.build_embedding_backend") as backend,
        patch("trace_search.indexing.wiki_indexer.WikiIndexer") as indexer,
    ):
        result = CliRunner().invoke(
            main,
            ["--mode", "bm25", "--baseline-dir", str(baseline_dir), "--quality-only"],
        )
    assert result.exit_code == 1
    assert "Missing battle baselines: api_bm25.json" in result.output
    backend.assert_not_called()
    indexer.assert_not_called()


def test_malformed_unselected_baseline_is_not_silently_ignored(tmp_path):
    baseline_dir = tmp_path / "baselines"
    shutil.copytree(BASELINES, baseline_dir)
    path = baseline_dir / "api_semantic.json"
    data = json.loads(path.read_text())
    data["total_queries"] = 0
    path.write_text(json.dumps(data))
    with patch("trace_search.indexing.embeddings.build_embedding_backend") as backend:
        result = CliRunner().invoke(
            main,
            ["--mode", "bm25", "--baseline-dir", str(baseline_dir), "--quality-only"],
        )
    assert result.exit_code == 1
    assert "Invalid battle baseline api_semantic.json" in result.output
    backend.assert_not_called()


@pytest.mark.parametrize(
    "baseline_dir,extra_args,expected",
    [
        (BASELINES, ["--top-k", "10"], "top_k"),
        (CHALLENGE_BASELINES, [], "queryset_fingerprint"),
    ],
)
def test_incompatible_inputs_fail_before_model(baseline_dir, extra_args, expected):
    with patch("trace_search.indexing.embeddings.build_embedding_backend") as backend:
        result = CliRunner().invoke(
            main,
            [
                "--mode",
                "bm25",
                "--baseline-dir",
                str(baseline_dir),
                "--quality-only",
                *extra_args,
            ],
        )
    assert result.exit_code == 1
    assert "Incompatible battle baseline" in result.output
    assert expected in result.output
    backend.assert_not_called()


def test_mislabelled_mode_baseline_fails_before_model(tmp_path):
    baseline_dir = tmp_path / "baselines"
    shutil.copytree(BASELINES, baseline_dir)
    shutil.copyfile(baseline_dir / "api_semantic.json", baseline_dir / "api_bm25.json")
    with patch("trace_search.indexing.embeddings.build_embedding_backend") as backend:
        result = CliRunner().invoke(
            main,
            ["--mode", "bm25", "--baseline-dir", str(baseline_dir), "--quality-only"],
        )
    assert result.exit_code == 1
    assert "report mode does not match its filename" in result.output
    backend.assert_not_called()


def test_top5_only_regression_identifies_the_query(tmp_path):
    references = {
        name: load_baseline(BASELINES / f"{name}_bm25.json")
        for name in ("retrieval", "support", "api")
    }
    reference = references["retrieval"]
    result = next(row for row in reference.results if not row.top_1_path_hit and row.top_5_path_hit)
    changed = result.model_copy(
        update={
            "top_5_path_hit": False,
            "path_first_hit_rank": None,
            "path_reciprocal_rank": 0.0,
            "path_hit_within_max_rank": False,
        }
    )
    current = EvaluationReport.from_results(
        timestamp=reference.timestamp,
        manifest=reference.manifest,
        results=[changed if row.query_id == changed.query_id else row for row in reference.results],
    )
    with (
        patch("trace_search.indexing.embeddings.build_embedding_backend"),
        patch("trace_search.indexing.wiki_indexer.WikiIndexer"),
        patch(
            "tools.eval.battle_royale.run_evaluation",
            side_effect=[current, references["support"], references["api"]],
        ),
    ):
        outcome = CliRunner().invoke(
            main,
            [
                "--mode",
                "bm25",
                "--baseline-dir",
                str(BASELINES),
                "--quality-only",
                "--output-dir",
                str(tmp_path),
                "--label",
                "top5",
            ],
        )
    assert outcome.exit_code == 1, outcome.output
    assert f"retrieval/bm25 query {changed.query_id}: lost Top-5," in outcome.output


def test_repeated_mode_cannot_overwrite_an_evaluation():
    with patch("trace_search.indexing.embeddings.build_embedding_backend") as backend:
        result = CliRunner().invoke(main, ["--mode", "bm25", "--mode", "bm25"])
    assert result.exit_code == 2
    assert "Search modes must be unique" in result.output
    backend.assert_not_called()
