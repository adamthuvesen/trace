"""Tests for evaluation CLI option composition."""

from pathlib import Path

from tools.eval.battle_royale import load_suite
from tools.eval.cli import resolve_eval_scope
from tools.eval.evaluator import evaluate_query, percentile
from tools.eval.models import GoldenQuery


def test_stress_scope_disables_quick_filter():
    quick_only, stress_only, include_stress = resolve_eval_scope(
        quick=False,
        full=False,
        include_stress=False,
        stress=True,
        ci_stress=False,
    )

    assert quick_only is False
    assert stress_only is True
    assert include_stress is False


def test_ci_stress_scope_disables_quick_filter():
    quick_only, stress_only, include_stress = resolve_eval_scope(
        quick=False,
        full=False,
        include_stress=True,
        stress=False,
        ci_stress=True,
    )

    assert quick_only is False
    assert stress_only is True
    assert include_stress is False


def test_default_scope_is_quick():
    quick_only, stress_only, include_stress = resolve_eval_scope(
        quick=False,
        full=False,
        include_stress=False,
        stress=False,
        ci_stress=False,
    )

    assert quick_only is True
    assert stress_only is False
    assert include_stress is False


def test_percentile_is_bounded_for_tiny_samples():
    values = [1.0, 2.0]

    assert percentile(values, 50) == 1.5
    assert 1.0 <= percentile(values, 95) <= 2.0
    assert 1.0 <= percentile(values, 99) <= 2.0


def test_reranked_eval_mode_forces_rerank():
    class FakeHybrid:
        rerank_value = None

        def search(self, query, top_k=5, rerank=None):
            self.rerank_value = rerank
            return [
                {
                    "path": "api/webhooks.md",
                    "content": "webhook signature event",
                    "score": 1.0,
                }
            ]

    searcher = FakeHybrid()
    query = GoldenQuery(
        id="rerank",
        query="verify event notification",
        category="rerank",
        expected_path="api/webhooks.md",
        expected_keywords=["signature"],
    )

    result = evaluate_query(query, searcher, "reranked")

    assert searcher.rerank_value is True
    assert result.top_1_path_hit
    assert result.category == "rerank"


def test_golden_query_coerces_keyword_values_to_strings():
    query = GoldenQuery.from_dict(
        {
            "id": "numeric-keyword",
            "query": "HTTP 429 retry",
            "category": "hybrid",
            "expected_path": "api/rate-limits.md",
            "expected_keywords": [429, "Retry-After"],
        }
    )

    assert query.expected_keywords == ["429", "Retry-After"]


def test_battle_suite_resolves_fixture_paths():
    description, kbs, modes = load_suite(Path("tests/fixtures/eval_battle_royale.yaml"))

    assert description
    assert {"retrieval", "support", "api"} == {kb.kb_id for kb in kbs}
    assert "reranked" in modes
    assert all(kb.kb_path.exists() for kb in kbs)
