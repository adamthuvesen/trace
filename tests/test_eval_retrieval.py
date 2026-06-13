"""End-to-end retrieval checks for tools.eval (requires embedding model)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from trace_search.config import get_settings
from trace_search.indexer import WikiIndexer
from trace_search.search import SemanticSearch
from tools.eval.evaluator import run_evaluation
from tools.eval.models import GoldenQuery

FIXTURE_KB = Path(__file__).parent / "fixtures" / "eval_kb"
FIXTURE_GOLDEN = Path(__file__).parent / "fixtures" / "eval_golden_queries.yaml"


@pytest.fixture
def eval_indexer(tmp_path: Path) -> WikiIndexer:
    get_settings.cache_clear()
    SemanticSearch._embedding_cache.clear()
    indexer = WikiIndexer(
        kb_path=FIXTURE_KB,
        chroma_path=tmp_path / "chroma",
        bm25_path=tmp_path / "bm25",
    )
    indexer.build_index(force=True)
    SemanticSearch._embedding_cache.clear()
    yield indexer
    get_settings.cache_clear()
    SemanticSearch._embedding_cache.clear()


@pytest.mark.slow
def test_run_evaluation_reports_reciprocal_rank(
    eval_indexer: WikiIndexer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Uses tests/fixtures/eval_golden_queries.yaml (same file as the CLI smoke corpus)."""
    monkeypatch.setenv("EVAL_GOLDEN_QUERIES", str(FIXTURE_GOLDEN.resolve()))
    get_settings.cache_clear()
    # Semantic mode keeps chunk text on the hit; hybrid may route short queries to
    # BM25 hits whose corpus payload can omit body text.
    report = run_evaluation(
        eval_indexer,
        search_mode="semantic",
        quick_only=False,
        stress_only=False,
        include_stress=False,
    )
    assert report.total_queries == 17
    assert report.mean_reciprocal_rank > 0.0
    by_id = {r.query_id: r for r in report.results}
    assert by_id["easy-bm25"].path_first_hit_rank == 1
    assert by_id["easy-bm25"].path_reciprocal_rank == pytest.approx(1.0)
    stress_report = run_evaluation(
        eval_indexer,
        search_mode="semantic",
        stress_only=True,
        include_stress=False,
    )
    assert stress_report.total_queries == 2
    sb = {r.query_id: r for r in stress_report.results}
    assert isinstance(sb["stress-bm25"].path_hit_within_max_rank, bool)
    get_settings.cache_clear()


@pytest.mark.slow
@patch("tools.eval.evaluator.load_golden_queries")
def test_strict_keywords_requires_all_terms(
    mock_load, eval_indexer: WikiIndexer
) -> None:
    mock_load.return_value = [
        GoldenQuery(
            id="kw-test",
            query="BM25 overview",
            category="concepts",
            expected_path="glossary/bm25.md",
            expected_keywords=["BM25", "keyword", "ranking", "nonexistent-term-xyz"],
        ),
    ]
    loose = run_evaluation(
        eval_indexer,
        search_mode="semantic",
        strict_keywords=False,
    )
    strict = run_evaluation(
        eval_indexer,
        search_mode="semantic",
        strict_keywords=True,
    )
    assert loose.top_1_keyword_accuracy == 1.0
    assert strict.top_1_keyword_accuracy == 0.0
