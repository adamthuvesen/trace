"""Format search results for MCP and CLI output."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from trace_search.retrieval.search_types import SearchRoute


def _query_terms(query: str) -> list[str]:
    """Extract meaningful lowercase terms for hints and snippets."""
    return [
        term for term in re.findall(r"[A-Za-z0-9_/-]+", query.lower()) if len(term) > 1
    ]


def _trim_at_boundary(text: str, limit: int) -> str:
    """Trim text at a readable boundary."""
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    cut = compact.rfind(" ", 0, limit)
    return compact[: cut if cut > 0 else limit].rstrip() + "..."


def _best_quote(content: str, query: str, limit: int = 360) -> str | None:
    """Extract a concise quote-ready snippet."""
    compact = re.sub(r"\s+", " ", content).strip()
    if not compact:
        return None

    terms = _query_terms(query)
    lowered = compact.lower()
    positions = [lowered.find(term) for term in terms if lowered.find(term) >= 0]
    if positions:
        pos = min(positions)
        start = max(0, pos - 120)
        end = min(len(compact), pos + limit - 120)
        snippet = compact[start:end]
        if start > 0:
            snippet = "..." + snippet
        if end < len(compact):
            snippet += "..."
        return _trim_at_boundary(snippet, limit)

    return _trim_at_boundary(compact, limit)


def _normalization_key(text: str) -> str:
    """Normalize text for near-duplicate suppression."""
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()[:220]


def _score_for_sort(hit: dict[str, Any]) -> float:
    score = hit.get("rerank_score", hit.get("rrf_score", hit.get("score", 0)))
    return float(score or 0)


def _format_followups(hits: list[dict[str, Any]], limit: int = 3) -> list[str]:
    seen: set[tuple[str | None, str]] = set()
    followups: list[str] = []
    for hit in hits:
        path = hit.get("path")
        if not path:
            continue
        collection = hit.get("collection")
        key = (collection, str(path))
        if key in seen:
            continue
        seen.add(key)
        if collection:
            followups.append(
                f'- `get_document(path="{path}", collection="{collection}")`'
            )
        else:
            followups.append(f'- `get_document(path="{path}")`')
        if len(followups) >= limit:
            break
    return followups


def _format_empty_results(route: SearchRoute | None) -> str:
    if route is None:
        return "No results found."

    lines = [
        "No results found.",
        "",
        f"**Strategy:** {route.strategy}",
        f"**Reason:** {route.reason}",
    ]
    if not route.filters.is_empty:
        lines.append(f"**Active filters:** {route.filters.describe()}")
    return "\n".join(lines)


def _append_route_summary(lines: list[str], route: SearchRoute | None) -> None:
    if route is None:
        return

    fallback = "yes" if route.fallback_used else "no"
    lines.extend(
        [
            "",
            "## Strategy",
            f"- **Selected:** {route.strategy}",
            f"- **Fallback used:** {fallback}",
            f"- **Reason:** {route.reason}",
        ]
    )
    if not route.filters.is_empty:
        lines.append(f"- **Active filters:** {route.filters.describe()}")


def _group_hits_by_document(
    sorted_hits: list[dict[str, Any]],
    *,
    max_documents: int,
) -> list[list[dict[str, Any]]]:
    grouped: dict[tuple[str | None, str], list[dict[str, Any]]] = defaultdict(list)
    for hit in sorted_hits:
        grouped[(hit.get("collection"), str(hit.get("path", "")))].append(hit)

    return sorted(
        grouped.values(),
        key=lambda group: max(_score_for_sort(hit) for hit in group),
        reverse=True,
    )[:max_documents]


def _matched_query_terms(query: str, quote: str) -> list[str]:
    quote_lower = quote.lower()
    return [term for term in _query_terms(query) if term in quote_lower]


def _append_snippet(
    lines: list[str],
    *,
    hit: dict[str, Any],
    title: str,
    query: str,
    quote: str,
    snippet_number: int,
) -> None:
    breadcrumb = hit.get("breadcrumb") or title
    lines.append("")
    lines.append(f"**Snippet {snippet_number}:** {breadcrumb}")

    hints = hit.get("match_hints") or []
    if hints:
        lines.append(f"- **Match evidence:** {'; '.join(hints[:3])}")

    matched_terms = _matched_query_terms(query, quote)
    if matched_terms:
        terms = ", ".join(f"`{term}`" for term in sorted(set(matched_terms)))
        lines.append(f"- **Matched terms:** {terms}")

    lines.append(f"- **Best quote:** {quote}")

    neighbor = hit.get("neighbor_content")
    if neighbor:
        lines.append(f"- **Nearby context:** {_trim_at_boundary(str(neighbor), 220)}")


def _append_document_group(
    lines: list[str],
    *,
    index: int,
    group: list[dict[str, Any]],
    query: str,
    global_seen: set[tuple[str | None, str]],
    dedupe_across_documents: bool,
    max_snippets: int,
) -> None:
    first = group[0]
    path = str(first.get("path", ""))
    title = first.get("title") or path or "Untitled"
    collection = first.get("collection")
    source = first.get("source", "unknown")
    folder = first.get("folder", "")

    lines.append("")
    lines.append(f"### {index}. {title}")
    lines.append(f"- **Path:** `{path}`")
    if collection:
        lines.append(f"- **Collection:** {collection}")
    if folder:
        lines.append(f"- **Folder:** {folder}")
    lines.append(f"- **Source:** {source}")

    per_doc_seen: set[str] = set()
    snippets_added = 0
    for hit in group:
        quote = _best_quote(str(hit.get("content", "")), query)
        if not quote:
            continue

        normalized = _normalization_key(quote)
        global_key = (collection, normalized)
        if normalized in per_doc_seen:
            continue
        if dedupe_across_documents and global_key in global_seen:
            continue

        per_doc_seen.add(normalized)
        global_seen.add(global_key)
        snippets_added += 1
        _append_snippet(
            lines,
            hit=hit,
            title=title,
            query=query,
            quote=quote,
            snippet_number=snippets_added,
        )

        if snippets_added >= max_snippets:
            break


def format_search_context(
    hits: list[dict[str, Any]],
    *,
    query: str,
    route: SearchRoute | None = None,
    max_documents: int = 5,
    max_snippets_per_document: int = 2,
) -> str:
    """Render grouped search context for agents."""
    if not hits:
        return _format_empty_results(route)

    sorted_hits = sorted(hits, key=_score_for_sort, reverse=True)
    lines = [f"Found {len(hits)} results"]
    _append_route_summary(lines, route)

    document_groups = _group_hits_by_document(
        sorted_hits,
        max_documents=max_documents,
    )
    lines.extend(["", "## Context"])
    global_seen: set[tuple[str | None, str]] = set()
    for index, group in enumerate(document_groups, 1):
        _append_document_group(
            lines,
            index=index,
            group=group,
            query=query,
            global_seen=global_seen,
            dedupe_across_documents=len(document_groups) > 1,
            max_snippets=max_snippets_per_document,
        )

    followups = _format_followups(sorted_hits)
    if followups:
        lines.extend(["", "## Suggested Follow-ups"])
        lines.extend(followups)

    return "\n".join(lines)


def format_results(hits: list[dict[str, Any]], include_content: bool = True) -> str:
    """Format search results for display."""
    if not hits:
        return "No results found."

    lines = [f"Found {len(hits)} results:\n"]

    for i, hit in enumerate(hits, 1):
        score_str = (
            f"{hit.get('score', 0):.3f}"
            if isinstance(hit.get("score"), float)
            else str(hit.get("score", ""))
        )
        source = hit.get("source", "unknown")

        lines.append(f"---\n### {i}. {hit['title']}")
        lines.append(f"**Path:** `{hit['path']}`")
        if "collection" in hit:
            lines.append(f"**Collection:** {hit['collection']}")
        lines.append(f"**Folder:** {hit['folder']}")

        if source == "keyword":
            lines.append(f"**BM25 Score:** {score_str}")
        elif source == "semantic":
            lines.append(f"**Similarity:** {score_str}")
        elif source == "hybrid":
            rrf = hit.get("rrf_score", 0)
            rerank = hit.get("rerank_score")
            if rerank is not None:
                lines.append(f"**Rerank Score:** {rerank:.3f} (RRF: {rrf:.4f})")
            else:
                lines.append(f"**RRF Score:** {rrf:.4f}")

        if include_content:
            content = _trim_at_boundary(hit.get("content", ""), 500)
            lines.append(f"\n**Preview:**\n{content}\n")

    return "\n".join(lines)
