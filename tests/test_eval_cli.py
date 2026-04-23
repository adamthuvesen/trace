"""Tests for evaluation CLI option composition."""

from tools.eval.cli import resolve_eval_scope
from tools.eval.evaluator import percentile


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
