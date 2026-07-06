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
#     "numpy>=1.26.0",
#     "pydantic-settings>=2.0.0",
# ]
# ///
"""Benchmark embedding models for Trace search.

Compares retrieval accuracy and query latency between supported models.

Usage:
    uv run tools/benchmark_models.py [--quick]
"""

from __future__ import annotations

import argparse
import gc
import logging
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from trace_search.indexing.wiki_indexer import WikiIndexer
    from trace_search.retrieval.search import (
        SemanticSearch,
        KeywordSearch,
        HybridSearch,
    )

SEED = 42


# === CORE SEARCH CONCEPTS ===
QUERIES_CORE = [
    ("What is BM25?", ["BM25", "keyword", "ranking"]),
    ("What is RRF?", ["RRF", "rank", "fusion"]),
    ("What is ANN search?", ["ANN", "nearest neighbor", "vector"]),
    ("What is hybrid search?", ["hybrid search", "semantic", "keyword"]),
    (
        "What are the key search quality metrics?",
        ["precision", "recall", "latency", "coverage"],
    ),
]

# === INDEXING & PARSING ===
QUERIES_INDEXING = [
    (
        "How does heading-based chunking work?",
        ["heading-based", "chunking", "sections"],
    ),
    ("What is chunk overlap?", ["overlap", "chunk", "context"]),
    ("How does partial reindexing work?", ["partial reindex", "changed", "documents"]),
    (
        "How do extractors handle frontmatter?",
        ["frontmatter", "metadata", "extract"],
    ),
    ("What file formats are supported?", ["supported formats", "markdown", "pdf"]),
    ("How does OCR fallback work?", ["OCR", "fallback", "scanned"]),
    ("How are duplicate paths handled?", ["duplicate", "path", "index"]),
]

# === FEATURES ===
QUERIES_FEATURES = [
    (
        "What is multi-collection search?",
        ["multi-collection", "collections", "search"],
    ),
    ("What is reranking?", ["reranking", "results", "relevance"]),
    ("What is query expansion?", ["query expansion", "synonyms", "terms"]),
    ("What is the result preview panel?", ["preview", "snippet", "results"]),
    ("What AI features exist?", ["AI", "feature", "assistant"]),
]

# === DOCUMENTATION ===
QUERIES_DOCS = [
    ("What is the writing style guide?", ["style guide", "writing", "docs"]),
    (
        "How does the documentation review checklist work?",
        ["documentation review", "checklist", "docs"],
    ),
    (
        "What are the editorial principles?",
        ["editorial principles", "clarity", "consistency"],
    ),
    ("How do release notes work?", ["release notes", "changes", "version"]),
    ("How do deprecation notices work?", ["deprecation", "notice", "migration"]),
]

# === CONFIGURATION ===
QUERIES_CONFIG = [
    (
        "How do I configure multiple collections?",
        ["multiple collections", "KB_COLLECTIONS", "paths"],
    ),
    ("How do I set KB_PATH?", ["KB_PATH", "knowledge base", "path"]),
    ("How do I override INDEX_PATH?", ["INDEX_PATH", "index", "path"]),
    ("How do I enable embedding warmup?", ["embedding warmup", "warmup", "startup"]),
]

# === SECURITY & PRIVACY ===
QUERIES_SECURITY = [
    (
        "What are information security standards?",
        ["information security", "standards", "data"],
    ),
    ("How does access control work?", ["access control", "permissions", "role"]),
    ("What is the privacy policy?", ["privacy", "policy", "data"]),
]

# === NAVIGATION ===
QUERIES_NAVIGATION = [
    ("Where is the getting started guide?", ["getting started", "guide", "setup"]),
    ("Where is the API reference?", ["API reference", "reference", "endpoints"]),
    ("Where is the troubleshooting guide?", ["troubleshooting", "guide", "errors"]),
]

# === EVALUATION & OBSERVABILITY ===
QUERIES_EVALUATION = [
    ("How does benchmark reporting work?", ["benchmark", "report", "latency"]),
    ("What is the latency budget?", ["latency budget", "p95", "p99"]),
    ("How do relevance tests work?", ["relevance tests", "top-1", "top-5"]),
    (
        "How do notebook exports support analysis?",
        ["notebook export", "analysis", "data"],
    ),
]

# === SUPPORT WORKFLOWS ===
QUERIES_SUPPORT = [
    ("How does issue triage work?", ["issue triage", "bug", "priority"]),
    ("What is the change log process?", ["change log", "release", "history"]),
    ("How do privacy requests work?", ["privacy request", "data", "deletion"]),
]

# === FILE TYPE & LONG QUERIES ===
QUERIES_FILE_TYPES = [
    ("Markdown frontmatter reference", ["markdown", "frontmatter", "metadata"]),
    ("PDF extraction troubleshooting", ["PDF", "extraction", "troubleshooting"]),
    ("Slide deck conversion workflow", ["slide deck", "conversion", "slides"]),
    ("SQL model reference examples", ["SQL", "model", "reference"]),
    ("YAML configuration examples", ["YAML", "configuration", "examples"]),
    ("Notebook export metadata", ["notebook", "export", "metadata"]),
    ("Unicode heading parsing rules", ["Unicode", "heading", "parsing"]),
    ("Large table rendering limits", ["table", "rendering", "limits"]),
    ("Code fence extraction behavior", ["code fence", "extraction", "behavior"]),
    ("Archive import manifest format", ["archive", "import", "manifest"]),
    ("Image alt text guidelines", ["image", "alt text", "guidelines"]),
    ("CLI transcript parsing examples", ["CLI", "transcript", "parsing"]),
]

# === TECHNICAL PLATFORM ===
QUERIES_TECHNICAL = [
    ("API authentication patterns", ["API", "authentication", "integration"]),
    ("Batch reindex CLI usage", ["batch reindex", "CLI", "usage"]),
    (
        "Natural language query rewriting",
        ["natural language", "query", "rewriting"],
    ),
    ("Parser pipeline architecture", ["parser", "pipeline", "architecture"]),
    ("Index size optimization", ["index", "size", "optimization"]),
    ("Comparing vector backends", ["vector", "backend", "comparison"]),
    ("Telemetry event streams", ["telemetry", "event", "implementation"]),
]

# === COMPARISONS ===
QUERIES_COMPARISONS = [
    (
        "Markdown vs notebooks for knowledge docs",
        ["markdown", "notebook", "docs"],
    ),
    (
        "Chunk overlap vs chunk size tradeoffs",
        ["overlap", "chunk size", "tradeoff"],
    ),
    (
        "Keyword search vs semantic search",
        ["keyword search", "semantic search", "comparison"],
    ),
    ("JSON vs YAML configuration", ["JSON", "YAML", "configuration"]),
]

# === PLANNING & ROADMAPS ===
QUERIES_PLANNING = [
    (
        "Documentation roadmap themes",
        ["documentation roadmap", "themes", "priorities"],
    ),
    (
        "Search quality improvement plan",
        ["search quality", "improvement", "plan"],
    ),
    ("Platform migration checklist", ["migration", "checklist", "platform"]),
    ("Observability rollout plan", ["observability", "rollout", "plan"]),
    ("Deprecation cleanup milestones", ["deprecation", "cleanup", "milestones"]),
]

# === ACRONYM-HEAVY QUERIES ===
QUERIES_ACRONYMS = [
    ("BM25 and RRF ranking flow", ["BM25", "RRF", "ranking"]),
    ("ANN and HNSW indexing", ["ANN", "HNSW", "indexing"]),
    ("API and CLI integration setup", ["API", "CLI", "integration"]),
    ("OCR for PDF ingestion", ["OCR", "PDF", "ingestion"]),
    ("SSO and SAML configuration", ["SSO", "SAML", "configuration"]),
    ("SDK and API versioning", ["SDK", "API", "versioning"]),
]

# === NATURAL LANGUAGE / SEMANTIC QUERIES ===
QUERIES_SEMANTIC = [
    ("Finding docs about stale indexes", ["stale", "index", "freshness"]),
    ("Improving result snippets for search", ["snippet", "search", "results"]),
    ("Preparing for a docs migration", ["docs", "migration", "prepare"]),
    (
        "Reducing false positives in retrieval",
        ["false positives", "retrieval", "precision"],
    ),
    (
        "Finding roadmap updates for search quality",
        ["roadmap", "search quality", "updates"],
    ),
    (
        "Tools for inspecting parsed documents",
        ["tools", "parsed documents", "inspection"],
    ),
]

# === EDGE CASES ===
QUERIES_EDGE_CASES = [
    ("SQL examples for reporting", ["SQL", "reporting", "queries"]),
    ("Unicode normalization in search", ["Unicode", "normalization", "search"]),
    (
        "Binary attachment extraction limits",
        ["binary attachment", "extraction", "limits"],
    ),
    (
        "Duplicate filename disambiguation",
        ["duplicate filename", "disambiguation", "path"],
    ),
    ("Nested folder indexing behavior", ["nested folder", "indexing", "behavior"]),
    ("Partial reindex after rename", ["partial reindex", "rename", "path"]),
    (
        "Third-party parser safeguards",
        ["third-party parser", "safeguards", "security"],
    ),
]

# === RANKING & DEBUGGING ===
QUERIES_RANKING = [
    ("Ranking debug checklist", ["ranking", "debug", "checklist"]),
    ("Result fusion tuning", ["result fusion", "tuning", "weights"]),
    (
        "Regression benchmark methodology",
        ["regression benchmark", "methodology", "baseline"],
    ),
    ("Recall failure analysis", ["recall", "failure", "analysis"]),
    ("Snippet truncation behavior", ["snippet", "truncation", "behavior"]),
    ("Relevance threshold tuning", ["relevance threshold", "tuning", "score"]),
]

# === GOVERNANCE & COMPLIANCE ===
QUERIES_GOVERNANCE = [
    ("Disaster recovery testing", ["disaster recovery", "testing", "backup"]),
    (
        "Data retention and privacy compliance",
        ["data retention", "compliance", "privacy"],
    ),
    ("Role-based access control", ["access control", "role", "RBAC"]),
    ("Security incident response", ["incident", "response", "security"]),
    ("Audit logging requirements", ["audit", "logging", "monitoring"]),
]

TEST_QUERIES_FULL = (
    QUERIES_CORE
    + QUERIES_INDEXING
    + QUERIES_FEATURES
    + QUERIES_DOCS
    + QUERIES_CONFIG
    + QUERIES_SECURITY
    + QUERIES_NAVIGATION
    + QUERIES_EVALUATION
    + QUERIES_SUPPORT
    + QUERIES_FILE_TYPES
    + QUERIES_TECHNICAL
    + QUERIES_COMPARISONS
    + QUERIES_PLANNING
    + QUERIES_ACRONYMS
    + QUERIES_SEMANTIC
    + QUERIES_EDGE_CASES
    + QUERIES_RANKING
    + QUERIES_GOVERNANCE
)

# Quick subset (representative sample from each category)
TEST_QUERIES_QUICK = [
    QUERIES_CORE[0],
    QUERIES_INDEXING[0],
    QUERIES_FEATURES[0],
    QUERIES_DOCS[0],
    QUERIES_CONFIG[0],
    QUERIES_SECURITY[0],
    QUERIES_NAVIGATION[0],
    QUERIES_EVALUATION[0],
    QUERIES_SUPPORT[0],
    QUERIES_FILE_TYPES[0],
    QUERIES_FILE_TYPES[7],
    QUERIES_FILE_TYPES[9],
    QUERIES_TECHNICAL[0],
    QUERIES_COMPARISONS[0],
    QUERIES_PLANNING[0],
    QUERIES_ACRONYMS[0],
    QUERIES_SEMANTIC[0],
    QUERIES_EDGE_CASES[0],
    QUERIES_RANKING[0],
    QUERIES_GOVERNANCE[0],
]


@dataclass
class FileTypeCoverage:
    extension: str
    file_count: int
    chunk_count: int
    hit_rate: float


@dataclass
class BenchmarkResult:
    model_name: str
    chunk_count: int
    top_1_accuracy: float
    top_5_accuracy: float
    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    index_size_mb: float
    build_time_s: float
    file_type_coverage: dict[str, FileTypeCoverage] | None = None


def get_dir_size_mb(path: Path) -> float:
    if not path.exists():
        return 0.0
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return total / (1024 * 1024)


def analyze_file_type_coverage(
    indexer: WikiIndexer,
    searcher: SemanticSearch | KeywordSearch | HybridSearch,
    test_queries: list[tuple[str, list[str]]],
    search_mode: str = "semantic",
) -> dict[str, FileTypeCoverage]:
    """Analyze which file types are indexed and retrieved."""
    all_data = indexer.collection.get(include=["metadatas"])
    metadatas = all_data["metadatas"]

    ext_file_count: dict[str, set[str]] = defaultdict(set)
    ext_chunk_count: dict[str, int] = defaultdict(int)

    for meta in metadatas:
        path = meta.get("path", "")
        ext = Path(path).suffix.lower()
        if ext:
            ext_file_count[ext].add(path)
            ext_chunk_count[ext] += 1

    ext_hits: dict[str, int] = defaultdict(int)
    total_queries = len(test_queries)

    for query, _ in test_queries:
        if search_mode == "bm25":
            hits = searcher.search(query, max_results=5)
        else:
            hits = searcher.search(query, top_k=5)
        seen_exts = set()
        for hit in hits[:5]:
            ext = Path(hit["path"]).suffix.lower()
            if ext and ext not in seen_exts:
                ext_hits[ext] += 1
                seen_exts.add(ext)

    coverage = {}
    all_exts = set(ext_chunk_count.keys()) | set(ext_hits.keys())

    for ext in sorted(all_exts):
        coverage[ext] = FileTypeCoverage(
            extension=ext,
            file_count=len(ext_file_count.get(ext, set())),
            chunk_count=ext_chunk_count.get(ext, 0),
            hit_rate=ext_hits.get(ext, 0) / total_queries if total_queries > 0 else 0.0,
        )

    return coverage


def _activate_model(model_name: str):
    """Reload settings for a specific embedding model within this process."""
    from trace_search import config as config_module
    from trace_search.indexing import wiki_indexer as wiki_indexer_module
    from trace_search.retrieval import search as search_module

    os.environ["EMBEDDING_MODEL"] = model_name
    config_module.get_settings.cache_clear()
    new_settings = config_module.get_settings()
    config_module.settings = new_settings
    wiki_indexer_module.settings = new_settings
    search_module.settings = new_settings
    return new_settings


def benchmark_model(
    model_name: str,
    test_queries: list[tuple[str, list[str]]],
    latency_iterations: int = 3,
    search_mode: str = "semantic",
) -> BenchmarkResult:
    """Benchmark a single embedding model."""
    from trace_search.config import SUPPORTED_MODELS
    from trace_search.indexing.wiki_indexer import WikiIndexer
    from trace_search.retrieval.search import (
        SemanticSearch,
        KeywordSearch,
        HybridSearch,
    )

    mode_suffix = f" ({search_mode})" if search_mode != "semantic" else ""
    logger.info(f"\n{'=' * 60}")
    logger.info(f"Benchmarking: {model_name}{mode_suffix}")
    logger.info("=" * 60)

    if model_name not in SUPPORTED_MODELS:
        raise ValueError(f"Unknown model: {model_name}")

    settings = _activate_model(model_name)
    logger.info(f"Dimensions: {settings.embedding_dims}")

    # Use persistent index (not temp directory)
    indexer = WikiIndexer()
    logger.info(f"ChromaDB: {indexer.chroma_path}")
    logger.info(f"BM25: {indexer.bm25_path}")

    if indexer.collection.count() == 0:
        logger.info("\nBuilding index (first time)...")
        build_start = time.perf_counter()
        chunk_count = indexer.build_index()
        build_time = time.perf_counter() - build_start
        logger.info(f"Build time: {build_time:.1f}s")
    else:
        chunk_count = indexer.collection.count()
        build_time = 0.0
        logger.info(f"Using existing index: {chunk_count} chunks")

    chroma_size = get_dir_size_mb(indexer.chroma_path)
    bm25_size = get_dir_size_mb(indexer.bm25_path)
    total_size = chroma_size + bm25_size
    logger.info(
        f"Index size: {total_size:.1f} MB (ChromaDB: {chroma_size:.1f}, BM25: {bm25_size:.1f})"
    )

    logger.info(f"\nTesting retrieval accuracy (mode: {search_mode})...")

    if search_mode == "semantic":
        searcher = SemanticSearch(indexer.collection, indexer.backend)
        SemanticSearch._embedding_cache.clear()
        SemanticSearch._cache_hits = 0
        SemanticSearch._cache_misses = 0
    elif search_mode == "bm25":
        searcher = KeywordSearch(indexer)
    elif search_mode == "hybrid":
        searcher = HybridSearch(indexer, indexer.backend)
    else:
        raise ValueError(f"Unknown search mode: {search_mode}")

    top_1_hits = 0
    top_5_hits = 0

    for query, expected_keywords in test_queries:
        if search_mode == "bm25":
            hits = searcher.search(query, max_results=5)
        else:
            hits = searcher.search(query, top_k=5)

        if hits:
            top_content = hits[0]["content"].lower()
            if sum(1 for k in expected_keywords if k.lower() in top_content) >= 2:
                top_1_hits += 1

            all_content = " ".join(h["content"].lower() for h in hits[:5])
            if sum(1 for k in expected_keywords if k.lower() in all_content) >= 2:
                top_5_hits += 1

    top_1_accuracy = top_1_hits / len(test_queries)
    top_5_accuracy = top_5_hits / len(test_queries)

    logger.info(f"Top-1 accuracy: {top_1_accuracy:.1%}")
    logger.info(f"Top-5 accuracy: {top_5_accuracy:.1%}")

    logger.info(f"\nMeasuring query latency ({latency_iterations} iterations)...")
    latencies = []

    SemanticSearch._embedding_cache.clear()

    for _ in range(latency_iterations):
        for query, _ in test_queries:
            # Clear cache to measure cold query time
            SemanticSearch._embedding_cache.clear()

            start = time.perf_counter()
            if search_mode == "bm25":
                searcher.search(query, max_results=10)
            else:
                searcher.search(query, top_k=10)
            latencies.append((time.perf_counter() - start) * 1000)

    latencies_sorted = sorted(latencies)
    n = len(latencies_sorted)
    p50_idx = min(n // 2, n - 1)
    p95_idx = min(int(n * 0.95), n - 1)
    p99_idx = min(int(n * 0.99), n - 1)

    latency_p50 = latencies_sorted[p50_idx]
    latency_p95 = latencies_sorted[p95_idx]
    latency_p99 = latencies_sorted[p99_idx]

    logger.info(f"Latency p50: {latency_p50:.1f}ms")
    logger.info(f"Latency p95: {latency_p95:.1f}ms")
    logger.info(f"Latency p99: {latency_p99:.1f}ms")

    logger.info("\nAnalyzing file type coverage...")
    file_type_coverage = analyze_file_type_coverage(
        indexer, searcher, test_queries, search_mode
    )

    logger.info("\nFile type coverage:")
    for ext, cov in file_type_coverage.items():
        logger.info(
            f"  {ext}: {cov.file_count} files, {cov.chunk_count} chunks, "
            f"{cov.hit_rate:.1%} hit rate"
        )

    gc.collect()

    display_name = (
        f"{model_name} ({search_mode})" if search_mode != "semantic" else model_name
    )

    return BenchmarkResult(
        model_name=display_name,
        chunk_count=chunk_count,
        top_1_accuracy=top_1_accuracy,
        top_5_accuracy=top_5_accuracy,
        latency_p50_ms=latency_p50,
        latency_p95_ms=latency_p95,
        latency_p99_ms=latency_p99,
        index_size_mb=total_size,
        build_time_s=build_time,
        file_type_coverage=file_type_coverage,
    )


def print_comparison_table(results: list[BenchmarkResult]) -> None:
    logger.info("\n" + "=" * 80)
    logger.info("MODEL COMPARISON RESULTS")
    logger.info("=" * 80)

    header = (
        f"{'Model':<30} | {'Top-1':>6} | {'Top-5':>6} | "
        f"{'p50 (ms)':>8} | {'p95 (ms)':>8} | {'Size (MB)':>9} | {'Build (s)':>9}"
    )
    logger.info(header)
    logger.info("-" * 80)

    for r in results:
        row = (
            f"{r.model_name:<30} | {r.top_1_accuracy:>5.1%} | {r.top_5_accuracy:>5.1%} | "
            f"{r.latency_p50_ms:>8.1f} | {r.latency_p95_ms:>8.1f} | "
            f"{r.index_size_mb:>9.1f} | {r.build_time_s:>9.1f}"
        )
        logger.info(row)

    logger.info("-" * 80)

    if len(results) > 1:
        best_top1 = max(results, key=lambda r: r.top_1_accuracy)
        best_top5 = max(results, key=lambda r: r.top_5_accuracy)
        best_latency = min(results, key=lambda r: r.latency_p50_ms)
        best_size = min(results, key=lambda r: r.index_size_mb)

        logger.info("\nBest by metric:")
        logger.info(
            f"  Top-1 accuracy: {best_top1.model_name} ({best_top1.top_1_accuracy:.1%})"
        )
        logger.info(
            f"  Top-5 accuracy: {best_top5.model_name} ({best_top5.top_5_accuracy:.1%})"
        )
        logger.info(
            f"  Query latency:  {best_latency.model_name} ({best_latency.latency_p50_ms:.1f}ms p50)"
        )
        logger.info(
            f"  Index size:     {best_size.model_name} ({best_size.index_size_mb:.1f}MB)"
        )

        logger.info("\n" + "-" * 40)
        logger.info("RECOMMENDATION:")

        # Prioritize accuracy, then latency
        if best_top1.top_1_accuracy >= 0.8 and best_top1.latency_p95_ms <= 150:
            logger.info(
                f"  Use {best_top1.model_name} - best accuracy with acceptable latency"
            )
        elif best_latency.top_1_accuracy >= 0.75:
            logger.info(
                f"  Use {best_latency.model_name} - good accuracy with fastest queries"
            )
        else:
            logger.info(f"  Use {best_top1.model_name} - prioritize accuracy")

    if results and results[0].file_type_coverage:
        print_file_type_coverage(results[0])


def print_file_type_coverage(result: BenchmarkResult) -> None:
    if not result.file_type_coverage:
        return

    logger.info("\n" + "=" * 80)
    logger.info("FILE TYPE COVERAGE ANALYSIS")
    logger.info("=" * 80)

    coverage = result.file_type_coverage

    document_types = {".md", ".pdf", ".docx", ".pptx"}
    code_types = {".sql", ".py", ".yml", ".yaml", ".ipynb", ".ts", ".tsx"}

    header = f"{'Extension':<10} | {'Files':>6} | {'Chunks':>7} | {'Hit Rate':>9} | {'Status':<15}"
    logger.info(header)
    logger.info("-" * 60)

    missing_types = []
    low_coverage_types = []

    for ext in sorted(document_types | code_types):
        if ext in coverage:
            cov = coverage[ext]
            status = "OK" if cov.hit_rate > 0 else "NO HITS"
            if cov.hit_rate == 0 and cov.chunk_count > 0:
                low_coverage_types.append(ext)
            row = f"{ext:<10} | {cov.file_count:>6} | {cov.chunk_count:>7} | {cov.hit_rate:>8.1%} | {status:<15}"
        else:
            status = "NOT INDEXED"
            missing_types.append(ext)
            row = f"{ext:<10} | {0:>6} | {0:>7} | {'N/A':>9} | {status:<15}"
        logger.info(row)

    extra_types = set(coverage.keys()) - document_types - code_types
    if extra_types:
        logger.info("\nAdditional file types in index:")
        for ext in sorted(extra_types):
            cov = coverage[ext]
            logger.info(f"  {ext}: {cov.file_count} files, {cov.chunk_count} chunks")

    logger.info("\n" + "-" * 40)
    if missing_types:
        logger.info(
            f"WARNING: File types NOT in index: {', '.join(sorted(missing_types))}"
        )
    if low_coverage_types:
        logger.info(
            f"WARNING: File types with 0% hit rate: {', '.join(sorted(low_coverage_types))}"
        )

    docs_indexed = sum(
        1 for t in document_types if t in coverage and coverage[t].chunk_count > 0
    )
    docs_hit = sum(
        1 for t in document_types if t in coverage and coverage[t].hit_rate > 0
    )

    logger.info(f"\nDocument types indexed: {docs_indexed}/{len(document_types)}")
    logger.info(f"Document types retrieved: {docs_hit}/{len(document_types)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark embedding models")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Run quick benchmark with fewer queries",
    )
    parser.add_argument(
        "--model",
        type=str,
        help="Benchmark specific model only",
    )
    parser.add_argument(
        "--search-mode",
        type=str,
        choices=["semantic", "bm25", "hybrid", "all"],
        default="semantic",
        help="Search mode to benchmark (default: semantic, use 'all' to test all modes)",
    )
    args = parser.parse_args()

    from trace_search.config import settings, SUPPORTED_MODELS

    models_to_test = [args.model] if args.model else list(SUPPORTED_MODELS.keys())
    test_queries = TEST_QUERIES_QUICK if args.quick else TEST_QUERIES_FULL

    if args.search_mode == "all":
        search_modes = ["semantic", "bm25", "hybrid"]
    else:
        search_modes = [args.search_mode]

    logger.info("Trace Search Model Benchmark")
    logger.info(f"Knowledge base: {settings.kb_path}")
    logger.info(f"Models to test: {models_to_test}")
    logger.info(f"Search modes: {search_modes}")
    logger.info(f"Test queries: {len(test_queries)}")
    logger.info(f"Mode: {'quick' if args.quick else 'full'}")

    results = []
    for model in models_to_test:
        for mode in search_modes:
            try:
                result = benchmark_model(model, test_queries, search_mode=mode)
                results.append(result)
            except FileNotFoundError as e:
                logger.error(f"Knowledge base not found: {e}")
                sys.exit(1)
            except ValueError as e:
                logger.error(f"Configuration error for {model} ({mode}): {e}")
            except Exception as e:
                logger.exception(f"Failed to benchmark {model} ({mode}): {e}")

    if results:
        print_comparison_table(results)

    logger.info("\nBenchmark complete.")


if __name__ == "__main__":
    main()
