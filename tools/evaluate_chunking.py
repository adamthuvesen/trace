#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "chromadb>=0.4.0",
#     "sentence-transformers>=2.2.0",
#     "bm25s>=0.2.0",
#     "PyStemmer>=2.2.0",
#     "pymupdf>=1.24.0",
#     "python-docx>=1.0.0",
#     "python-pptx>=0.6.0",
#     "matplotlib>=3.8.0",
#     "numpy>=1.26.0",
#     "pydantic-settings>=2.0.0",
# ]
# ///
"""Test suite for evaluating chunking optimality in wiki search.

This module provides four test approaches:
1. Retrieval Quality Test - Check if chunks containing answers are retrieved
2. Chunk Size Distribution Analysis - Analyze chunk size balance
3. Semantic Coherence Inspection - Check if related concepts stay together
4. Chunk Strategy Comparison - Compare different chunking approaches

Usage:
    uv run tools/evaluate_chunking.py [command]

Commands:
    retrieval   Run retrieval quality test
    sizes       Run chunk size distribution analysis
    coherence   Run semantic coherence inspection
    compare     Compare different chunk strategies
    all         Run all tests (default)
    report      Generate full report with visualizations
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from trace_search.config import settings
from trace_search.indexer import WikiIndexer, chunk_by_headings

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).parent / "test_output"
SEED = 42


# --- Test Data ---


@dataclass
class TestQuery:
    query: str
    expected_keywords: list[str]
    expected_paths: list[str] = field(default_factory=list)
    description: str = ""


TEST_QUERIES = [
    # Core Search Concepts
    TestQuery(
        query="What is BM25?",
        expected_keywords=["BM25", "keyword", "ranking", "terms"],
        description="BM25 ranking overview",
    ),
    TestQuery(
        query="What is RRF?",
        expected_keywords=["RRF", "rank", "fusion", "reciprocal"],
        description="RRF result fusion overview",
    ),
    TestQuery(
        query="What is ANN search?",
        expected_keywords=["ANN", "nearest neighbor", "vector", "index"],
        description="ANN search definition",
    ),
    TestQuery(
        query="What is hybrid search?",
        expected_keywords=["hybrid search", "semantic", "keyword", "results"],
        description="Hybrid search overview",
    ),
    TestQuery(
        query="What are the key search quality metrics?",
        expected_keywords=["precision", "recall", "latency", "coverage", "quality"],
        description="Search quality metrics",
    ),
    # Indexing & Parsing
    TestQuery(
        query="How does heading-based chunking work?",
        expected_keywords=["heading-based", "chunking", "sections", "markdown"],
        description="Heading-based chunking",
    ),
    TestQuery(
        query="What is chunk overlap?",
        expected_keywords=["overlap", "chunk", "context", "window"],
        description="Chunk overlap behavior",
    ),
    TestQuery(
        query="How does partial reindexing work?",
        expected_keywords=["partial reindex", "changed", "documents", "update"],
        description="Partial reindex workflow",
    ),
    TestQuery(
        query="How do extractors handle frontmatter?",
        expected_keywords=["frontmatter", "metadata", "extract", "parser"],
        description="Frontmatter extraction",
    ),
    TestQuery(
        query="What file formats are supported?",
        expected_keywords=["supported formats", "markdown", "pdf", "docx"],
        description="Supported file formats",
    ),
    # Features & Configuration
    TestQuery(
        query="What is multi-collection search?",
        expected_keywords=["multi-collection", "collections", "search", "federated"],
        description="Multi-collection search",
    ),
    TestQuery(
        query="What is reranking?",
        expected_keywords=["reranking", "results", "relevance", "ordering"],
        description="Reranking behavior",
    ),
    TestQuery(
        query="What is query expansion?",
        expected_keywords=["query expansion", "synonyms", "terms", "rewritten"],
        description="Query expansion",
    ),
    TestQuery(
        query="How do I set KB_PATH?",
        expected_keywords=["KB_PATH", "knowledge base", "path", "environment"],
        description="KB_PATH configuration",
    ),
    TestQuery(
        query="How do I override INDEX_PATH?",
        expected_keywords=["INDEX_PATH", "index", "path", "storage"],
        description="INDEX_PATH configuration",
    ),
    # Documentation & Navigation
    TestQuery(
        query="What is the writing style guide?",
        expected_keywords=["style guide", "writing", "docs", "tone"],
        description="Writing style guide",
    ),
    TestQuery(
        query="How does the documentation review checklist work?",
        expected_keywords=["documentation review", "checklist", "accuracy", "links"],
        description="Documentation review checklist",
    ),
    TestQuery(
        query="How do release notes work?",
        expected_keywords=["release notes", "changes", "version", "highlights"],
        description="Release notes workflow",
    ),
    TestQuery(
        query="Where is the API reference?",
        expected_keywords=["API reference", "reference", "endpoints", "schema"],
        description="API reference location",
    ),
    TestQuery(
        query="Where is the troubleshooting guide?",
        expected_keywords=["troubleshooting", "guide", "errors", "fixes"],
        description="Troubleshooting guide",
    ),
    # Evaluation & Platform
    TestQuery(
        query="How does benchmark reporting work?",
        expected_keywords=["benchmark", "report", "latency", "summary"],
        description="Benchmark reporting",
    ),
    TestQuery(
        query="What is the latency budget?",
        expected_keywords=["latency budget", "p95", "p99", "target"],
        description="Latency budget targets",
    ),
    TestQuery(
        query="How does parser pipeline architecture work?",
        expected_keywords=["parser", "pipeline", "architecture", "stages"],
        description="Parser pipeline architecture",
    ),
    TestQuery(
        query="What are event instrumentation guidelines?",
        expected_keywords=["event instrumentation", "tracking", "event", "schema"],
        description="Event instrumentation guidelines",
    ),
    TestQuery(
        query="How do notebook exports support analysis?",
        expected_keywords=["notebook export", "analysis", "metadata", "cells"],
        description="Notebook export analysis",
    ),
    TestQuery(
        query="What is audit logging?",
        expected_keywords=["audit logging", "events", "trace", "monitoring"],
        description="Audit logging overview",
    ),
]


# --- Test 1: Retrieval Quality ---


@dataclass
class RetrievalResult:
    query: str
    top_1_hit: bool
    top_5_hit: bool
    top_result_path: str
    top_result_score: float
    keywords_found: list[str]
    keywords_missing: list[str]


def run_retrieval_quality_test(indexer: WikiIndexer, top_k: int = 5) -> dict[str, Any]:
    """Test if chunks containing answers are actually retrieved.

    Target: >80% hit rate at top-1, 100% at top-5.
    """
    from trace_search.retrieval.search import SemanticSearch

    logger.info("\n" + "=" * 60)
    logger.info("TEST 1: Retrieval Quality")
    logger.info("=" * 60)

    semantic = SemanticSearch(indexer.collection, indexer.backend)
    results: list[RetrievalResult] = []

    for tq in TEST_QUERIES:
        logger.info(f"\nQuery: '{tq.query}'")
        logger.info(f"  Expected: {tq.description}")

        hits = semantic.search(tq.query, top_k=top_k)

        if not hits:
            results.append(
                RetrievalResult(
                    query=tq.query,
                    top_1_hit=False,
                    top_5_hit=False,
                    top_result_path="(no results)",
                    top_result_score=0.0,
                    keywords_found=[],
                    keywords_missing=tq.expected_keywords,
                )
            )
            logger.info("  MISS: No results returned")
            continue

        top_content = hits[0]["content"].lower()
        top_1_keywords = [k for k in tq.expected_keywords if k.lower() in top_content]
        top_1_hit = len(top_1_keywords) >= 2

        all_content = " ".join(h["content"].lower() for h in hits[:5])
        top_5_keywords = [k for k in tq.expected_keywords if k.lower() in all_content]
        top_5_hit = len(top_5_keywords) >= 2

        result = RetrievalResult(
            query=tq.query,
            top_1_hit=top_1_hit,
            top_5_hit=top_5_hit,
            top_result_path=hits[0]["path"],
            top_result_score=hits[0]["score"],
            keywords_found=top_5_keywords,
            keywords_missing=[
                k for k in tq.expected_keywords if k.lower() not in all_content
            ],
        )
        results.append(result)

        status = "HIT" if top_1_hit else ("PARTIAL" if top_5_hit else "MISS")
        logger.info(f"  {status}: {hits[0]['path']} (score: {hits[0]['score']:.3f})")
        logger.info(f"  Keywords found: {top_5_keywords}")
        if result.keywords_missing:
            logger.info(f"  Keywords missing: {result.keywords_missing}")

    top_1_rate = sum(1 for r in results if r.top_1_hit) / len(results)
    top_5_rate = sum(1 for r in results if r.top_5_hit) / len(results)

    logger.info("\n" + "-" * 40)
    logger.info("RETRIEVAL QUALITY SUMMARY")
    logger.info("-" * 40)
    logger.info(f"Top-1 hit rate: {top_1_rate:.1%} (target: >80%)")
    logger.info(f"Top-5 hit rate: {top_5_rate:.1%} (target: 100%)")

    top_1_pass = top_1_rate >= 0.8
    top_5_pass = top_5_rate >= 1.0

    logger.info(f"Top-1 target: {'PASS' if top_1_pass else 'FAIL'}")
    logger.info(f"Top-5 target: {'PASS' if top_5_pass else 'FAIL'}")

    return {
        "top_1_hit_rate": top_1_rate,
        "top_5_hit_rate": top_5_rate,
        "top_1_target_pass": top_1_pass,
        "top_5_target_pass": top_5_pass,
        "total_queries": len(results),
        "results": [
            {
                "query": r.query,
                "top_1_hit": r.top_1_hit,
                "top_5_hit": r.top_5_hit,
                "top_result_path": r.top_result_path,
                "top_result_score": r.top_result_score,
                "keywords_found": r.keywords_found,
                "keywords_missing": r.keywords_missing,
            }
            for r in results
        ],
    }


# --- Test 2: Chunk Size Distribution ---


def run_chunk_size_analysis(
    indexer: WikiIndexer, save_plot: bool = True
) -> dict[str, Any]:
    """Analyze chunk size distribution for balance.

    Flags if heavily skewed and suggests adjustments.
    """
    logger.info("\n" + "=" * 60)
    logger.info("TEST 2: Chunk Size Distribution")
    logger.info("=" * 60)

    all_data = indexer.collection.get(include=["documents"])
    chunks = all_data["documents"]

    if not chunks:
        logger.warning("No chunks found in index")
        return {"error": "No chunks in index"}

    sizes = [len(c) for c in chunks]

    stats = {
        "count": len(sizes),
        "mean": statistics.mean(sizes),
        "median": statistics.median(sizes),
        "stdev": statistics.stdev(sizes) if len(sizes) > 1 else 0,
        "min": min(sizes),
        "max": max(sizes),
        "p25": np.percentile(sizes, 25),
        "p75": np.percentile(sizes, 75),
        "p95": np.percentile(sizes, 95),
    }

    logger.info(f"\nTotal chunks: {stats['count']}")
    logger.info(f"Mean size: {stats['mean']:.0f} chars")
    logger.info(f"Median size: {stats['median']:.0f} chars")
    logger.info(f"Std deviation: {stats['stdev']:.0f} chars")
    logger.info(f"Min/Max: {stats['min']} / {stats['max']} chars")
    logger.info(f"25th/75th percentile: {stats['p25']:.0f} / {stats['p75']:.0f} chars")
    logger.info(f"95th percentile: {stats['p95']:.0f} chars")

    skewness = (
        (stats["mean"] - stats["median"]) / stats["stdev"] if stats["stdev"] > 0 else 0
    )
    coefficient_of_variation = (
        stats["stdev"] / stats["mean"] if stats["mean"] > 0 else 0
    )

    logger.info(f"\nSkewness indicator: {skewness:.2f}")
    logger.info(f"Coefficient of variation: {coefficient_of_variation:.2f}")

    recommendations = []

    if stats["max"] > 4000:
        recommendations.append(
            f"Large chunks detected (max: {stats['max']}). Consider reducing max_chunk_chars."
        )

    if stats["min"] < 100:
        recommendations.append(
            f"Very small chunks detected (min: {stats['min']}). Consider merging tiny sections."
        )

    if coefficient_of_variation > 1.0:
        recommendations.append(
            "High variance in chunk sizes. Consider more aggressive splitting of large chunks."
        )

    if abs(skewness) > 0.5:
        direction = "right" if skewness > 0 else "left"
        recommendations.append(
            f"Distribution is skewed {direction}. May affect retrieval consistency."
        )

    buckets = {
        "tiny (<200)": sum(1 for s in sizes if s < 200),
        "small (200-500)": sum(1 for s in sizes if 200 <= s < 500),
        "medium (500-1000)": sum(1 for s in sizes if 500 <= s < 1000),
        "large (1000-2000)": sum(1 for s in sizes if 1000 <= s < 2000),
        "xlarge (>2000)": sum(1 for s in sizes if s >= 2000),
    }

    logger.info("\nSize distribution:")
    for bucket, count in buckets.items():
        pct = count / len(sizes) * 100
        logger.info(f"  {bucket}: {count} ({pct:.1f}%)")

    if recommendations:
        logger.info("\n" + "-" * 40)
        logger.info("RECOMMENDATIONS:")
        for rec in recommendations:
            logger.info(f"  - {rec}")
    else:
        logger.info("\n  Distribution looks balanced.")

    if save_plot:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        plot_path = OUTPUT_DIR / "chunk_size_distribution.png"

        fig, axes = plt.subplots(1, 2, figsize=(12, 5))

        axes[0].hist(sizes, bins=50, edgecolor="black", alpha=0.7)
        axes[0].axvline(
            stats["mean"], color="r", linestyle="--", label=f"Mean: {stats['mean']:.0f}"
        )
        axes[0].axvline(
            stats["median"],
            color="g",
            linestyle="--",
            label=f"Median: {stats['median']:.0f}",
        )
        axes[0].set_xlabel("Chunk Size (chars)")
        axes[0].set_ylabel("Frequency")
        axes[0].set_title("Chunk Size Distribution")
        axes[0].legend()

        axes[1].boxplot(sizes, vert=True)
        axes[1].set_ylabel("Chunk Size (chars)")
        axes[1].set_title("Chunk Size Box Plot")

        plt.tight_layout()
        plt.savefig(plot_path, dpi=150)
        plt.close()

        logger.info(f"\nPlot saved to: {plot_path}")

    return {
        "statistics": stats,
        "buckets": buckets,
        "skewness_indicator": skewness,
        "coefficient_of_variation": coefficient_of_variation,
        "recommendations": recommendations,
        "is_balanced": len(recommendations) == 0,
    }


# --- Test 3: Semantic Coherence ---


def run_semantic_coherence_inspection(
    indexer: WikiIndexer, sample_size: int = 5
) -> dict[str, Any]:
    """Inspect if semantically related concepts stay together.

    Samples documents and reviews their chunks for coherence.
    """
    logger.info("\n" + "=" * 60)
    logger.info("TEST 3: Semantic Coherence Inspection")
    logger.info("=" * 60)

    docs = indexer.load_documents()

    if not docs:
        return {"error": "No documents found"}

    # Diverse sample: one doc per folder, then fill with random picks
    np.random.seed(SEED)
    folders = list({d["folder"] for d in docs if d["folder"]})
    sample_docs = []

    for folder in folders[:sample_size]:
        folder_docs = [d for d in docs if d["folder"] == folder]
        if folder_docs:
            sample_docs.append(np.random.choice(folder_docs))

    while len(sample_docs) < sample_size and len(sample_docs) < len(docs):
        doc = np.random.choice(docs)
        if doc not in sample_docs:
            sample_docs.append(doc)

    results = []

    for doc in sample_docs:
        logger.info(f"\n--- Document: {doc['title']} ---")
        logger.info(f"Path: {doc['path']}")
        logger.info(f"Folder: {doc['folder']}")
        logger.info(f"Total content length: {len(doc['content'])} chars")

        # Get chunks for this document
        chunks = chunk_by_headings(doc["content"])

        logger.info(f"Number of chunks: {len(chunks)}")

        chunk_analysis = []
        for i, chunk in enumerate(chunks):
            headings = re.findall(r"^(#{1,3})\s+(.+)$", chunk, re.MULTILINE)
            heading_levels = [(len(h[0]), h[1]) for h in headings]

            # Mixed heading levels often signal unrelated sections combined
            levels = [h[0] for h in heading_levels]
            has_mixed_levels = len(set(levels)) > 1 if levels else False

            chunk_info = {
                "index": i,
                "size": len(chunk),
                "headings": heading_levels,
                "has_mixed_levels": has_mixed_levels,
                "preview": chunk[:100].replace("\n", " ") + "...",
            }
            chunk_analysis.append(chunk_info)

            logger.info(f"\n  Chunk {i}: {len(chunk)} chars")
            if heading_levels:
                logger.info(f"    Headings: {[h[1][:30] for h in heading_levels]}")
            if has_mixed_levels:
                logger.info(
                    "    WARNING: Mixed heading levels (may combine unrelated sections)"
                )

        issues = []

        tiny_chunks = [c for c in chunk_analysis if c["size"] < 200]
        if tiny_chunks:
            issues.append(
                f"Found {len(tiny_chunks)} tiny chunks (<200 chars) - may lose context"
            )

        mixed_chunks = [c for c in chunk_analysis if c["has_mixed_levels"]]
        if mixed_chunks:
            issues.append(f"Found {len(mixed_chunks)} chunks with mixed heading levels")

        if len(chunks) == 1 and len(doc["content"]) > 2000:
            issues.append("Large document not split - may overwhelm retrieval")

        results.append(
            {
                "path": doc["path"],
                "title": doc["title"],
                "folder": doc["folder"],
                "content_length": len(doc["content"]),
                "chunk_count": len(chunks),
                "chunks": chunk_analysis,
                "issues": issues,
            }
        )

        if issues:
            logger.info("\n  Issues:")
            for issue in issues:
                logger.info(f"    - {issue}")
        else:
            logger.info("\n  No coherence issues detected")

    total_issues = sum(len(r["issues"]) for r in results)
    docs_with_issues = sum(1 for r in results if r["issues"])

    logger.info("\n" + "-" * 40)
    logger.info("COHERENCE SUMMARY")
    logger.info("-" * 40)
    logger.info(f"Documents sampled: {len(results)}")
    logger.info(f"Documents with issues: {docs_with_issues}")
    logger.info(f"Total issues found: {total_issues}")

    return {
        "documents_sampled": len(results),
        "documents_with_issues": docs_with_issues,
        "total_issues": total_issues,
        "results": results,
        "coherence_score": (len(results) - docs_with_issues) / len(results)
        if results
        else 0,
    }


# --- Test 4: Chunk Strategy Comparison ---


def create_temp_index(
    kb_path: str,
    max_chunk_chars: int,
    strategy_name: str,
    _temp_dirs: list[Path] | None = None,
) -> tuple[WikiIndexer, int]:
    """Create a temporary index with isolated chunk settings.

    Pass a list as _temp_dirs to collect temp paths for cleanup.
    """
    import tempfile

    from trace_search import indexer as indexer_module

    temp_root = Path(tempfile.mkdtemp(prefix=f"wiki_test_{strategy_name}_"))
    if _temp_dirs is not None:
        _temp_dirs.append(temp_root)

    chroma_path = temp_root / "chroma_db"
    bm25_path = temp_root / "bm25_index"

    # Monkey-patch chunk_by_headings to use different max_chunk_chars
    original_chunk = chunk_by_headings

    def patched_chunk(
        content: str,
        max_chunk_chars_override: int = max_chunk_chars,
    ) -> list[str]:
        return original_chunk(content, max_chunk_chars=max_chunk_chars_override)

    indexer = WikiIndexer(kb_path, str(chroma_path), str(bm25_path))

    original_func = indexer_module.chunk_by_headings
    indexer_module.chunk_by_headings = patched_chunk

    try:
        chunk_count = indexer.build_index(force=True)
    finally:
        indexer_module.chunk_by_headings = original_func

    return indexer, chunk_count


def run_chunk_strategy_comparison(
    sample_queries: list[str] | None = None,
) -> dict[str, Any]:
    """Compare different chunking strategies.

    Strategies:
    - Current: 1000 chars, heading-based
    - Smaller: 500 chars, heading-based
    - Larger: 2000 chars, heading-based
    """
    logger.info("\n" + "=" * 60)
    logger.info("TEST 4: Chunk Strategy Comparison")
    logger.info("=" * 60)
    logger.info(
        "\nNote: This test creates temporary indexes and may take several minutes."
    )

    if sample_queries is None:
        sample_queries = [tq.query for tq in TEST_QUERIES[:4]]

    strategies = [
        ("current_1000", 1000),
        ("smaller_500", 500),
        ("larger_2000", 2000),
    ]

    results = {}
    temp_dirs: list[Path] = []

    for strategy_name, max_chars in strategies:
        logger.info(
            f"\n--- Testing strategy: {strategy_name} (max {max_chars} chars) ---"
        )

        try:
            indexer, chunk_count = create_temp_index(
                str(settings.kb_path),
                max_chars,
                strategy_name,
                _temp_dirs=temp_dirs,
            )
            logger.info(f"Created index with {chunk_count} chunks")

            retrieval_results = run_retrieval_quality_test(indexer, top_k=5)

            all_data = indexer.collection.get(include=["documents"])
            sizes = [len(c) for c in all_data["documents"]]

            results[strategy_name] = {
                "max_chunk_chars": max_chars,
                "chunk_count": chunk_count,
                "top_1_hit_rate": retrieval_results["top_1_hit_rate"],
                "top_5_hit_rate": retrieval_results["top_5_hit_rate"],
                "mean_chunk_size": statistics.mean(sizes) if sizes else 0,
                "median_chunk_size": statistics.median(sizes) if sizes else 0,
            }

        except Exception as e:
            logger.error(f"Failed to test strategy {strategy_name}: {e}")
            results[strategy_name] = {"error": str(e)}

    for temp_dir in temp_dirs:
        try:
            shutil.rmtree(temp_dir)
        except Exception as e:
            logger.warning(f"Failed to clean up {temp_dir}: {e}")

    logger.info("\n" + "-" * 40)
    logger.info("STRATEGY COMPARISON SUMMARY")
    logger.info("-" * 40)

    for name, data in results.items():
        if "error" in data:
            logger.info(f"\n{name}: ERROR - {data['error']}")
        else:
            logger.info(f"\n{name}:")
            logger.info(f"  Chunks: {data['chunk_count']}")
            logger.info(f"  Top-1 hit rate: {data['top_1_hit_rate']:.1%}")
            logger.info(f"  Top-5 hit rate: {data['top_5_hit_rate']:.1%}")
            logger.info(f"  Mean size: {data['mean_chunk_size']:.0f} chars")

    valid_results = {k: v for k, v in results.items() if "error" not in v}
    if valid_results:
        best_top1 = max(
            valid_results.keys(), key=lambda k: valid_results[k]["top_1_hit_rate"]
        )
        best_top5 = max(
            valid_results.keys(), key=lambda k: valid_results[k]["top_5_hit_rate"]
        )

        logger.info(f"\nBest for Top-1: {best_top1}")
        logger.info(f"Best for Top-5: {best_top5}")

        results["recommendation"] = {
            "best_top1_strategy": best_top1,
            "best_top5_strategy": best_top5,
        }

    return results


# --- Report Generation ---


def generate_report(
    retrieval_results: dict | None = None,
    size_results: dict | None = None,
    coherence_results: dict | None = None,
    comparison_results: dict | None = None,
) -> str:
    """Generate a comprehensive report of all test results."""
    lines = [
        "# Wiki Search Chunking Evaluation Report",
        "",
        f"Generated: {__import__('datetime').datetime.now().isoformat()}",
        f"Embedding Model: {settings.embedding_model}",
        "",
    ]

    if retrieval_results:
        lines.extend(
            [
                "## 1. Retrieval Quality",
                "",
                f"- **Top-1 Hit Rate:** {retrieval_results['top_1_hit_rate']:.1%} (target: >80%)",
                f"- **Top-5 Hit Rate:** {retrieval_results['top_5_hit_rate']:.1%} (target: 100%)",
                f"- **Top-1 Pass:** {'Yes' if retrieval_results['top_1_target_pass'] else 'No'}",
                f"- **Top-5 Pass:** {'Yes' if retrieval_results['top_5_target_pass'] else 'No'}",
                "",
                "### Query Results",
                "",
                "| Query | Top-1 | Top-5 | Top Result |",
                "|-------|-------|-------|------------|",
            ]
        )
        for r in retrieval_results["results"]:
            top1 = "Y" if r["top_1_hit"] else "N"
            top5 = "Y" if r["top_5_hit"] else "N"
            path = (
                r["top_result_path"][:40] + "..."
                if len(r["top_result_path"]) > 40
                else r["top_result_path"]
            )
            lines.append(f"| {r['query'][:30]}... | {top1} | {top5} | {path} |")
        lines.append("")

    if size_results and "statistics" in size_results:
        stats = size_results["statistics"]
        lines.extend(
            [
                "## 2. Chunk Size Distribution",
                "",
                f"- **Total Chunks:** {stats['count']}",
                f"- **Mean Size:** {stats['mean']:.0f} chars",
                f"- **Median Size:** {stats['median']:.0f} chars",
                f"- **Std Dev:** {stats['stdev']:.0f} chars",
                f"- **Min/Max:** {stats['min']} / {stats['max']} chars",
                f"- **Is Balanced:** {'Yes' if size_results.get('is_balanced') else 'No'}",
                "",
                "### Size Buckets",
                "",
            ]
        )
        for bucket, count in size_results["buckets"].items():
            lines.append(f"- {bucket}: {count}")

        if size_results.get("recommendations"):
            lines.extend(["", "### Recommendations", ""])
            for rec in size_results["recommendations"]:
                lines.append(f"- {rec}")
        lines.append("")

    if coherence_results and "results" in coherence_results:
        lines.extend(
            [
                "## 3. Semantic Coherence",
                "",
                f"- **Documents Sampled:** {coherence_results['documents_sampled']}",
                f"- **Documents with Issues:** {coherence_results['documents_with_issues']}",
                f"- **Total Issues:** {coherence_results['total_issues']}",
                f"- **Coherence Score:** {coherence_results['coherence_score']:.1%}",
                "",
            ]
        )

        if any(r["issues"] for r in coherence_results["results"]):
            lines.extend(["### Issues Found", ""])
            for r in coherence_results["results"]:
                if r["issues"]:
                    lines.append(f"**{r['title']}** ({r['path']})")
                    for issue in r["issues"]:
                        lines.append(f"  - {issue}")
            lines.append("")

    if comparison_results:
        lines.extend(
            [
                "## 4. Chunk Strategy Comparison",
                "",
                "| Strategy | Chunks | Top-1 | Top-5 | Mean Size |",
                "|----------|--------|-------|-------|-----------|",
            ]
        )
        for name, data in comparison_results.items():
            if name == "recommendation" or "error" in data:
                continue
            lines.append(
                f"| {name} | {data['chunk_count']} | "
                f"{data['top_1_hit_rate']:.1%} | {data['top_5_hit_rate']:.1%} | "
                f"{data['mean_chunk_size']:.0f} |"
            )

        if "recommendation" in comparison_results:
            rec = comparison_results["recommendation"]
            lines.extend(
                [
                    "",
                    f"**Recommended for Top-1:** {rec['best_top1_strategy']}",
                    f"**Recommended for Top-5:** {rec['best_top5_strategy']}",
                ]
            )
        lines.append("")

    # Known Considerations
    lines.extend(
        [
            "## Known Considerations",
            "",
            "1. **Tokenizer compatibility:** Token-based chunking relies on a tokenizer for the active EMBEDDING_MODEL.",
            "   - Custom models may need explicit mapping to a tokenizer repo.",
            "",
            "2. **Comparison scope:** Strategy comparison only varies max_chunk_chars in heading-based chunking.",
            "   - It does not compare overlap or token-based settings.",
            "",
            "3. **Dataset drift:** Retrieval quality depends on the current KB contents.",
            "   - Re-run evaluation after major content changes.",
            "",
        ]
    )

    return "\n".join(lines)


# --- CLI ---


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test suite for evaluating chunking optimality",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="all",
        choices=["retrieval", "sizes", "coherence", "compare", "all", "report"],
        help="Test to run (default: all)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=OUTPUT_DIR,
        help="Output directory for results",
    )
    parser.add_argument(
        "--skip-compare",
        action="store_true",
        help="Skip chunk strategy comparison (slow)",
    )

    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    logger.info(f"Loading index from {settings.kb_path}...")
    indexer = WikiIndexer()
    indexer.build_index()  # Ensure index exists

    retrieval_results = None
    size_results = None
    coherence_results = None
    comparison_results = None

    if args.command in ("retrieval", "all", "report"):
        retrieval_results = run_retrieval_quality_test(indexer)
        with open(args.output / "retrieval_results.json", "w") as f:
            json.dump(retrieval_results, f, indent=2)

    if args.command in ("sizes", "all", "report"):
        size_results = run_chunk_size_analysis(indexer, save_plot=True)
        with open(args.output / "size_analysis.json", "w") as f:
            json.dump(size_results, f, indent=2, default=float)

    if args.command in ("coherence", "all", "report"):
        coherence_results = run_semantic_coherence_inspection(indexer)
        with open(args.output / "coherence_results.json", "w") as f:
            json.dump(coherence_results, f, indent=2)

    if args.command == "compare" or (
        args.command in ("all", "report") and not args.skip_compare
    ):
        comparison_results = run_chunk_strategy_comparison()
        with open(args.output / "comparison_results.json", "w") as f:
            json.dump(comparison_results, f, indent=2, default=float)

    if args.command == "report" or args.command == "all":
        report = generate_report(
            retrieval_results, size_results, coherence_results, comparison_results
        )
        report_path = args.output / "chunking_evaluation_report.md"
        with open(report_path, "w") as f:
            f.write(report)
        logger.info(f"\nReport saved to: {report_path}")

    logger.info("\nDone!")


if __name__ == "__main__":
    main()
