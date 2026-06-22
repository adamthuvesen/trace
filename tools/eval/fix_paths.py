#!/usr/bin/env python3
"""Tool to verify and fix expected paths in golden queries.

Usage:
    # Dry run - analyze and report
    uv run python -m tools.eval.fix_paths --dry-run

    # Apply high-confidence fixes automatically
    uv run python -m tools.eval.fix_paths --apply --confidence high

    # Apply all fixes (including medium confidence)
    uv run python -m tools.eval.fix_paths --apply --confidence medium

    # Show detailed output
    uv run python -m tools.eval.fix_paths --dry-run -v
"""

from __future__ import annotations

import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import click
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from tools.eval.evaluator import get_golden_queries_path, load_golden_queries

EVAL_DIR = Path(__file__).parent

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class PathFix:
    """A suggested path fix for a golden query."""

    query_id: str
    query: str
    old_path: str
    new_path: str
    confidence: str  # "high", "medium", "low"
    keyword_overlap: float  # 0.0 to 1.0
    keywords_matched: list[str] = field(default_factory=list)
    keywords_missing: list[str] = field(default_factory=list)
    reason: str = ""
    old_path_exists: bool = False
    new_path_exists: bool = False


def extract_path_keywords(path: str) -> set[str]:
    """Extract meaningful keywords from a file path.

    Strips file extension, Notion-style hex IDs (24+ chars), short words (< 3),
    and common stopwords.
    """
    path_no_ext = re.sub(r"\.[a-z]+$", "", path, flags=re.IGNORECASE)
    parts = re.split(r"[/\\_\-\s]+", path_no_ext)

    keywords = set()
    stopwords = {
        "of",
        "the",
        "and",
        "or",
        "for",
        "to",
        "in",
        "at",
        "a",
        "an",
        "on",
        "by",
    }

    for part in parts:
        if re.match(r"^[0-9a-f]{24,}$", part, re.IGNORECASE):
            continue
        if len(part) < 3:
            continue
        word = part.lower()
        if word in stopwords:
            continue
        keywords.add(word)

    return keywords


def calculate_keyword_overlap(
    expected_keywords: list[str],
    path: str,
) -> tuple[float, list[str], list[str]]:
    """Calculate how many expected keywords appear in the path.

    Returns:
        Tuple of (overlap_ratio, matched_keywords, missing_keywords)
    """
    if not expected_keywords:
        return 0.0, [], []

    path_lower = path.lower()
    matched = []
    missing = []

    for keyword in expected_keywords:
        keyword_lower = keyword.lower()
        if keyword_lower in path_lower:
            matched.append(keyword)
        else:
            missing.append(keyword)

    overlap = len(matched) / len(expected_keywords)
    return overlap, matched, missing


def determine_confidence(
    keyword_overlap: float,
    old_path_exists: bool,
    new_path_exists: bool,
    category_matches: bool,
) -> str:
    """Determine confidence level for a fix suggestion.

    High confidence (auto-apply safe):
    - New path exists AND one of:
      - Keyword overlap >= 90% (very high match)
      - Keyword overlap >= 75% AND old path doesn't exist
      - Keyword overlap >= 75% AND category matches

    Medium confidence (review recommended):
    - New path exists AND keyword overlap >= 50%

    Low confidence (manual review required):
    - Everything else
    """
    if not new_path_exists:
        return "low"

    if keyword_overlap >= 0.90:
        return "high"

    if keyword_overlap >= 0.75 and (not old_path_exists or category_matches):
        return "high"

    if keyword_overlap >= 0.50:
        return "medium"

    return "low"


def analyze_queries(
    kb_path: Path,
    search_mode: str = "hybrid",
) -> list[PathFix]:
    """Analyze all queries and return suggested fixes.

    Args:
        kb_path: Path to the knowledge base.
        search_mode: Search mode to use for retrieving results.

    Returns:
        List of PathFix suggestions for queries that don't match.
    """
    from trace_search.indexer import WikiIndexer
    from trace_search.retrieval.search import HybridSearch, KeywordSearch, SemanticSearch

    queries = load_golden_queries(quick_only=False, include_stress=True)
    logger.info("Analyzing %d golden queries...", len(queries))

    indexer = WikiIndexer()
    if indexer.collection.count() == 0:
        logger.info("Building index...")
        indexer.build_index()
    else:
        logger.info("Using existing index: %d chunks", indexer.collection.count())

    if search_mode == "semantic":
        searcher = SemanticSearch(indexer.collection, indexer.backend)
    elif search_mode == "bm25":
        searcher = KeywordSearch(indexer)
    else:
        searcher = HybridSearch(indexer, indexer.backend)

    fixes: list[PathFix] = []

    for i, query in enumerate(queries, 1):
        logger.debug("[%d/%d] Analyzing: %s", i, len(queries), query.query[:50])

        if search_mode == "bm25":
            hits = searcher.search(query.query, max_results=5)
        else:
            hits = searcher.search(query.query, top_k=5)

        if not hits:
            logger.warning("No results for query: %s", query.id)
            continue

        retrieved_path = hits[0]["path"]

        if query.matches_path(retrieved_path):
            continue

        overlap, matched, missing = calculate_keyword_overlap(
            query.expected_keywords,
            retrieved_path,
        )

        old_full_path = kb_path / query.expected_path
        new_full_path = kb_path / retrieved_path
        old_exists = old_full_path.exists()
        new_exists = new_full_path.exists()

        category_matches = _path_matches_category(retrieved_path, query.category)

        confidence = determine_confidence(
            keyword_overlap=overlap,
            old_path_exists=old_exists,
            new_path_exists=new_exists,
            category_matches=category_matches,
        )

        reasons = []
        if not old_exists:
            reasons.append("old path doesn't exist")
        if new_exists:
            reasons.append("new path exists")
        if overlap >= 0.75:
            reasons.append(f"high keyword match ({overlap:.0%})")
        elif overlap >= 0.50:
            reasons.append(f"medium keyword match ({overlap:.0%})")
        else:
            reasons.append(f"low keyword match ({overlap:.0%})")

        fix = PathFix(
            query_id=query.id,
            query=query.query,
            old_path=query.expected_path,
            new_path=retrieved_path,
            confidence=confidence,
            keyword_overlap=overlap,
            keywords_matched=matched,
            keywords_missing=missing,
            reason="; ".join(reasons),
            old_path_exists=old_exists,
            new_path_exists=new_exists,
        )
        fixes.append(fix)

    return fixes


def _path_matches_category(path: str, category: str) -> bool:
    """Check if path folder structure matches query category."""
    path_lower = path.lower()
    category_lower = category.lower()

    category_patterns = {
        "concepts": ["glossary", "search"],
        "indexing": ["indexing", "extract", "format"],
        "features": ["features", "search"],
        "config": ["config"],
        "docs": ["docs", "release", "writing"],
        "reference": ["reference", "troubleshooting"],
        "evaluation": ["evaluation", "benchmark", "latency"],
        "platform": ["platform", "parser"],
        "telemetry": ["telemetry", "event"],
        "exports": ["exports", "notebook"],
        "observability": ["observability", "audit", "logging"],
        "security": ["security", "privacy", "access"],
        "support": ["support", "issue", "triage"],
    }

    patterns = category_patterns.get(category_lower, [category_lower])
    return any(pattern in path_lower for pattern in patterns)


def apply_fixes(
    fixes: list[PathFix],
    confidence_threshold: str = "high",
) -> int:
    """Apply fixes to the resolved golden queries YAML (see get_golden_queries_path).

    Args:
        fixes: List of PathFix suggestions.
        confidence_threshold: Minimum confidence level to apply ("high", "medium", "low").

    Returns:
        Number of fixes applied.
    """
    confidence_order = {"high": 3, "medium": 2, "low": 1}
    min_confidence = confidence_order[confidence_threshold]
    applicable = [f for f in fixes if confidence_order[f.confidence] >= min_confidence]

    if not applicable:
        logger.info("No fixes to apply at confidence level: %s", confidence_threshold)
        return 0

    with open(get_golden_queries_path()) as f:
        data = yaml.safe_load(f)

    fix_map = {f.query_id: f for f in applicable}

    applied = 0
    for query in data.get("queries", []):
        query_id = query.get("id")
        if query_id in fix_map:
            fix = fix_map[query_id]
            old_path = query["expected_path"]
            query["expected_path"] = fix.new_path

            old_ext = Path(old_path).suffix
            new_ext = Path(fix.new_path).suffix
            if old_ext != new_ext:
                query["file_type"] = new_ext

            logger.info(
                "Fixed %s: %s -> %s", query_id, old_path[:50], fix.new_path[:50]
            )
            applied += 1

    with open(get_golden_queries_path(), "w") as f:
        yaml.dump(
            data,
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            width=1000,  # Prevent line wrapping
        )

    logger.info("Applied %d fixes to %s", applied, get_golden_queries_path())
    return applied


def generate_report(fixes: list[PathFix], verbose: bool = False) -> str:
    """Generate a human-readable report of suggested fixes."""
    lines = []
    lines.append("=" * 80)
    lines.append("PATH FIX ANALYSIS REPORT")
    lines.append("=" * 80)
    lines.append("")

    by_confidence = {"high": [], "medium": [], "low": []}
    for fix in fixes:
        by_confidence[fix.confidence].append(fix)

    lines.append("SUMMARY")
    lines.append("-" * 40)
    lines.append(f"Total queries needing fixes: {len(fixes)}")
    lines.append(f"  High confidence:   {len(by_confidence['high'])}")
    lines.append(f"  Medium confidence: {len(by_confidence['medium'])}")
    lines.append(f"  Low confidence:    {len(by_confidence['low'])}")
    lines.append("")

    for level in ["high", "medium", "low"]:
        level_fixes = by_confidence[level]
        if not level_fixes:
            continue

        lines.append(f"{level.upper()} CONFIDENCE FIXES ({len(level_fixes)})")
        lines.append("-" * 40)

        for fix in level_fixes:
            lines.append(f"  [{fix.query_id}] {fix.query[:60]}")
            lines.append(f"    Old: {fix.old_path[:70]}")
            lines.append(f"    New: {fix.new_path[:70]}")
            lines.append(
                f"    Keywords: {fix.keyword_overlap:.0%} ({len(fix.keywords_matched)}/{len(fix.keywords_matched) + len(fix.keywords_missing)})"
            )

            if verbose:
                lines.append(f"    Matched: {', '.join(fix.keywords_matched)}")
                if fix.keywords_missing:
                    lines.append(f"    Missing: {', '.join(fix.keywords_missing)}")
                lines.append(f"    Reason: {fix.reason}")
                lines.append(
                    f"    Old exists: {fix.old_path_exists}, New exists: {fix.new_path_exists}"
                )

            lines.append("")

        lines.append("")

    return "\n".join(lines)


@click.command()
@click.option(
    "--dry-run",
    is_flag=True,
    help="Analyze and report without making changes (default behavior)",
)
@click.option(
    "--apply",
    is_flag=True,
    help="Apply fixes to your local golden queries YAML (see golden_queries.example.yaml)",
)
@click.option(
    "--confidence",
    type=click.Choice(["high", "medium", "low"]),
    default="high",
    help="Minimum confidence level for fixes (default: high)",
)
@click.option(
    "--search",
    type=click.Choice(["semantic", "bm25", "hybrid"]),
    default="hybrid",
    help="Search mode to use (default: hybrid)",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Show detailed output",
)
def main(
    dry_run: bool,
    apply: bool,
    confidence: str,
    search: str,
    verbose: bool,
) -> None:
    """Verify and fix expected paths in golden queries."""
    if not apply:
        dry_run = True

    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    from trace_search.config import settings

    kb_path = Path(settings.kb_path)

    click.echo(f"Knowledge base: {kb_path}")
    click.echo(f"Search mode: {search}")
    click.echo()

    fixes = analyze_queries(kb_path, search_mode=search)

    if not fixes:
        click.echo("All queries already have correct expected paths!")
        return

    report = generate_report(fixes, verbose=verbose)
    click.echo(report)

    if apply and not dry_run:
        click.echo("=" * 80)
        click.echo(f"APPLYING FIXES (confidence >= {confidence})")
        click.echo("=" * 80)

        applied = apply_fixes(fixes, confidence_threshold=confidence)
        gq = get_golden_queries_path()
        click.echo()
        click.echo(f"Applied {applied} fixes to {gq}")
        click.echo()
        click.echo("Next steps:")
        click.echo(f"  1. Review the changes in {gq} (gitignored unless you opt in).")
        click.echo(
            "  2. Run evaluation: KB_PATH=... uv run python -m tools.eval.cli --full"
        )
        click.echo(
            "  3. Commit only if your team shares goldens; otherwise keep the file local."
        )
    else:
        click.echo("=" * 80)
        click.echo("DRY RUN - No changes made")
        click.echo("=" * 80)
        click.echo()
        click.echo("To apply high-confidence fixes:")
        click.echo("  uv run python -m tools.eval.fix_paths --apply --confidence high")
        click.echo()
        click.echo("To apply all fixes (including medium confidence):")
        click.echo(
            "  uv run python -m tools.eval.fix_paths --apply --confidence medium"
        )


if __name__ == "__main__":
    main()
