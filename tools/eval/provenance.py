"""Portable input identity for comparable evaluation reports."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from tools.eval.models import (
    EvaluationManifest,
    EvaluationScope,
    GoldenQuery,
    SearchMode,
)

if TYPE_CHECKING:
    from trace_search.indexing.wiki_indexer import WikiIndexer


def fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def source_identity() -> tuple[str, str]:
    root = Path(__file__).resolve().parents[2]
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    files = sorted([*root.glob("src/**/*.py"), *root.glob("tools/eval/*.py")])
    source = [
        (
            path.relative_to(root).as_posix(),
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in files
    ]
    return (
        revision.stdout.strip() if revision.returncode == 0 else "unavailable",
        fingerprint(source),
    )


def current_latency_environment() -> str:
    return f"{platform.system()}-{platform.machine()}-python{platform.python_version()}"


def build_manifest(
    indexer: WikiIndexer,
    queries: list[GoldenQuery],
    *,
    scope: EvaluationScope,
    search_mode: SearchMode,
    top_k: int,
    min_keywords: int,
    strict_keywords: bool,
    strict_keywords_top1: bool,
) -> EvaluationManifest:
    metadata = indexer.snapshot().metadata
    if metadata is None:
        raise ValueError("Evaluation requires index provenance. Rebuild the scratch index.")
    corpus = sorted((record.path, record.content_sha) for record in metadata.source_files)
    revision, source = source_identity()
    return EvaluationManifest(
        corpus_fingerprint=fingerprint(corpus),
        queryset_fingerprint=fingerprint([query.to_dict() for query in queries]),
        selected_query_ids=[query.id for query in queries],
        scope=scope,
        includes_stress_queries=any(query.stress_set for query in queries),
        search_mode=search_mode,
        top_k=top_k,
        min_keywords=min_keywords,
        strict_keywords=strict_keywords,
        strict_keywords_top1=strict_keywords_top1,
        build_recipe={
            **metadata.build_recipe,
            "recipe_fingerprint": metadata.recipe_fingerprint,
        },
        source_revision=revision,
        source_fingerprint=source,
        latency_environment=current_latency_environment(),
    )


def comparison_differences(
    current: EvaluationManifest | None,
    baseline: EvaluationManifest | None,
    *,
    compare_latency: bool = True,
) -> list[str]:
    if current is None or baseline is None:
        raise ValueError(
            "Cannot compare legacy reports without provenance. Re-run the baseline or use a reviewed, explicitly migrated baseline."
        )
    input_fields = (
        "corpus_fingerprint",
        "queryset_fingerprint",
        "selected_query_ids",
        "scope",
        "includes_stress_queries",
        "metric_version",
        "top_k",
        "min_keywords",
        "strict_keywords",
        "strict_keywords_top1",
        "latency_protocol",
    )
    changed = [name for name in input_fields if getattr(current, name) != getattr(baseline, name)]
    if compare_latency and current.latency_environment != baseline.latency_environment:
        changed.append("latency_environment (use --quality-only for cross-host quality comparison)")
    if changed:
        raise ValueError(
            "Incompatible evaluation inputs or measurement semantics: " + ", ".join(changed)
        )
    return [
        name
        for name in (
            "search_mode",
            "build_recipe",
            "source_revision",
            "source_fingerprint",
        )
        if getattr(current, name) != getattr(baseline, name)
    ]
