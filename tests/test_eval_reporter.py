"""Tests for evaluation report rendering."""

from tools.eval.models import (
    CategoryMetrics,
    EvaluationReport,
    FileTypeMetrics,
    QueryResult,
)
from tools.eval.reporter import generate_console_report, generate_markdown_report


def _sample_report() -> EvaluationReport:
    return EvaluationReport(
        timestamp="2026-06-30T10:00:00+00:00",
        search_mode="adaptive",
        embedding_model="all-MiniLM-L6-v2",
        total_queries=2,
        quick_set_only=False,
        top_1_path_accuracy=0.5,
        top_5_path_accuracy=1.0,
        top_1_keyword_accuracy=0.5,
        top_5_keyword_accuracy=1.0,
        latency_p50_ms=8.0,
        latency_p95_ms=14.0,
        latency_p99_ms=18.0,
        latency_mean_ms=9.5,
        by_category={
            "search": CategoryMetrics(
                category="search",
                query_count=2,
                top_1_path_hits=1,
                top_5_path_hits=2,
                top_1_keyword_hits=1,
                top_5_keyword_hits=2,
                avg_latency_ms=9.5,
            )
        },
        by_file_type={
            ".md": FileTypeMetrics(
                file_type=".md",
                query_count=2,
                top_1_path_hits=1,
                top_5_path_hits=2,
                avg_latency_ms=9.5,
            )
        },
        results=[
            QueryResult(
                query_id="hit",
                query="exact match",
                top_1_path_hit=True,
                top_5_path_hit=True,
                top_1_keyword_hit=True,
                top_5_keyword_hit=True,
                retrieved_path="search/bm25.md",
                retrieved_score=1.0,
                latency_ms=8.0,
            ),
            QueryResult(
                query_id="miss",
                query="paraphrased retrieval question",
                top_1_path_hit=False,
                top_5_path_hit=True,
                top_1_keyword_hit=False,
                top_5_keyword_hit=True,
                retrieved_path="search/semantic.md",
                retrieved_score=0.7,
                latency_ms=11.0,
            ),
        ],
        mean_reciprocal_rank=0.75,
        within_max_rank_path_accuracy=1.0,
        include_stress=True,
        strict_keywords=True,
        strict_keywords_top1=True,
        adaptive_fallback_rate=0.25,
    )


def test_markdown_report_keeps_section_contract():
    rendered = generate_markdown_report(_sample_report())

    assert "# Trace Search Evaluation Report" in rendered
    assert (
        "**Eval mode:** includes stress queries, strict keywords (top-1 scope)"
        in rendered
    )
    assert "## Overall Metrics" in rendered
    assert "| Top-1 Path Accuracy | 50.0%" in rendered
    assert "## By Category" in rendered
    assert "| search | 2 | 50% | 100% | 50% | 9.5ms |" in rendered
    assert "## Failed Queries (Top-1 Miss)" in rendered
    assert "| miss | paraphrased retrieval question | search/semantic.md |" in rendered


def test_console_report_keeps_section_contract():
    rendered = generate_console_report(_sample_report())

    assert "TRACE SEARCH EVALUATION REPORT" in rendered
    assert "Eval subset:     core + stress" in rendered
    assert "Keyword mode:    strict (top-1 body only)" in rendered
    assert "ACCURACY METRICS" in rendered
    assert "Top-1 Path:    50.0%" in rendered
    assert "BY CATEGORY" in rendered
    assert "search             2   50%  100%" in rendered
    assert "BY FILE TYPE" in rendered
    assert ".md            2   50%  100%" in rendered
