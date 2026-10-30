"""Format search results for MCP and CLI output."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence

from trace_search.retrieval.search_types import SearchHit, SearchRoute, SearchResponse


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


def _format_followups(hits: Sequence[SearchHit], limit: int = 3) -> list[str]:
    seen: set[tuple[str, str]] = set()
    followups: list[str] = []
    for hit in hits:
        path = hit.path
        if not path:
            continue
        collection = hit.collection
        key = (collection, path)
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
    hits: Sequence[SearchHit], *, max_documents: int
) -> list[list[SearchHit]]:
    grouped: dict[tuple[str, str], list[SearchHit]] = defaultdict(list)
    for hit in hits:
        grouped[(hit.collection, hit.path)].append(hit)
    return list(grouped.values())[:max_documents]


def _matched_query_terms(query: str, quote: str) -> list[str]:
    quote_lower = quote.lower()
    return [term for term in _query_terms(query) if term in quote_lower]


def _append_snippet(
    lines: list[str],
    *,
    hit: SearchHit,
    title: str,
    query: str,
    quote: str,
    snippet_number: int,
) -> None:
    breadcrumb = hit.metadata["breadcrumb"] or title
    lines.append("")
    lines.append(f"**Snippet {snippet_number}:** {breadcrumb}")

    if hit.match_hints:
        lines.append(f"- **Match evidence:** {'; '.join(hit.match_hints[:3])}")

    matched_terms = _matched_query_terms(query, quote)
    if matched_terms:
        terms = ", ".join(f"`{term}`" for term in sorted(set(matched_terms)))
        lines.append(f"- **Matched terms:** {terms}")

    lines.append(f"- **Best quote:** {quote}")

    if hit.neighbor_content:
        lines.append(
            f"- **Nearby context:** {_trim_at_boundary(hit.neighbor_content, 220)}"
        )


def _append_document_group(
    lines: list[str],
    *,
    index: int,
    group: list[SearchHit],
    query: str,
    global_seen: set[tuple[str, str]],
    dedupe_across_documents: bool,
    max_snippets: int,
) -> None:
    first = group[0]
    path = first.path
    title = first.metadata["title"] or path or "Untitled"
    collection = first.collection
    source = first.source
    folder = first.metadata["folder"]

    lines.append("")
    lines.append(f"### {index}. {title}")
    lines.append(f"- **Path:** `{path}`")
    if collection:
        lines.append(f"- **Collection:** {collection}")
    if folder:
        lines.append(f"- **Folder:** {folder}")
    lines.append(f"- **Source:** {source}")
    status = first.metadata.get("status")
    if status and status != "current":
        lines.append(f"- **Status:** {status}")
    if as_of := first.metadata.get("as_of"):
        lines.append(f"- **As of:** {as_of}")

    per_doc_seen: set[str] = set()
    snippets_added = 0
    for hit in group:
        quote = _best_quote(hit.content, query)
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
    response: SearchResponse,
    *,
    query: str,
    max_documents: int = 5,
    max_snippets_per_document: int = 2,
) -> str:
    """Render grouped search context for agents in the response's ranking order."""
    hits, route = response.hits, response.route
    if not hits:
        return _format_empty_results(route)

    lines = [f"Found {len(hits)} results"]
    _append_route_summary(lines, route)

    document_groups = _group_hits_by_document(hits, max_documents=max_documents)
    lines.extend(["", "## Context"])
    global_seen: set[tuple[str, str]] = set()
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

    followups = _format_followups(hits)
    if followups:
        lines.extend(["", "## Suggested Follow-ups"])
        lines.extend(followups)

    return "\n".join(lines)


def format_results(hits: Sequence[SearchHit], include_content: bool = True) -> str:
    """Format search results for display."""
    if not hits:
        return "No results found."

    lines = [f"Found {len(hits)} results:\n"]

    for i, hit in enumerate(hits, 1):
        score = hit.evidence.score
        score_str = f"{score:.3f}" if isinstance(score, float) else str(score)
        source = hit.source

        lines.append(f"---\n### {i}. {hit.metadata['title']}")
        lines.append(f"**Path:** `{hit.path}`")
        if hit.collection:
            lines.append(f"**Collection:** {hit.collection}")
        lines.append(f"**Folder:** {hit.metadata['folder']}")

        if source == "keyword":
            lines.append(f"**BM25 Score:** {score_str}")
        elif source == "semantic":
            lines.append(f"**Similarity:** {score_str}")
        elif source == "hybrid":
            rrf = hit.evidence.rrf_score or 0
            lines.append(f"**RRF Score:** {rrf:.4f}")

        if include_content:
            content = _trim_at_boundary(hit.content, 500)
            lines.append(f"\n**Preview:**\n{content}\n")

    return "\n".join(lines)
