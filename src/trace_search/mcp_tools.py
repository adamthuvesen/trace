"""FastMCP tool registration for multi-collection Trace servers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from trace_search.collection_registry import CollectionRegistry
from trace_search.operations import TraceOperations


def _build_multi_instructions(collection_names: list[str]) -> str:
    """Generate dynamic instructions listing available collections."""
    names = ", ".join(f'"{c}"' for c in collection_names)
    return f"""Knowledge search server with multiple collections: {names}.

Use these tools to search across knowledge bases:
- search: **DEFAULT** - Smart BM25-first search with semantic/hybrid fallback
- semantic_search: Find documents by meaning/concept (for vague natural language)
- search_hybrid: Combined semantic + keyword with ranking (slower, use if search fails)
- get_document: Retrieve full document content
- list_documents: Browse available documents by folder
- doctor: Diagnose configuration, visible documents, index health, and sample queries
- reindex: Update indexes after adding or changing documents (incremental; pass force=true to rebuild)

All search tools accept an optional `collection` parameter to target a specific
knowledge base. Omit it or pass "all" to search across all collections.

Start with `search` for most queries. It reports which strategy won and suggests
useful `get_document` follow-ups for top results.
"""


def build_multi_mcp(
    server_name: str,
    collections: dict[str, Path],
    index_root: Path | None = None,
    instructions: str | None = None,
) -> tuple[FastMCP, dict[str, Any]]:
    """Build a multi-collection FastMCP server."""
    registry = CollectionRegistry(collections, index_root)
    operations = TraceOperations(registry)

    if instructions is None:
        instructions = _build_multi_instructions(registry.collection_names)

    mcp = FastMCP(server_name, instructions=instructions)

    @mcp.tool()
    def search(
        query: str,
        top_k: int = 10,
        collection: str | None = None,
        path_prefix: list[str] | None = None,
        extensions: list[str] | None = None,
        since: str | None = None,
    ) -> str:
        """Search knowledge bases. Default: BM25-first with semantic/hybrid fallback.

        Set `collection` to target a specific knowledge base, or omit to search all.
        Optional filters: `path_prefix`, `extensions`, `since` (ISO 8601).
        """
        return operations.search(
            query,
            top_k,
            collection,
            path_prefix=path_prefix,
            extensions=extensions,
            since=since,
        )

    @mcp.tool()
    def semantic_search(
        query: str,
        top_k: int = 10,
        collection: str | None = None,
        path_prefix: list[str] | None = None,
        extensions: list[str] | None = None,
        since: str | None = None,
    ) -> str:
        """Search knowledge bases by semantic similarity."""
        return operations.semantic_search(
            query,
            top_k,
            collection,
            path_prefix=path_prefix,
            extensions=extensions,
            since=since,
        )

    @mcp.tool()
    def keyword_search(
        keyword: str,
        max_results: int = 20,
        collection: str | None = None,
        path_prefix: list[str] | None = None,
        extensions: list[str] | None = None,
        since: str | None = None,
    ) -> str:
        """Direct BM25 keyword search for exact terms, identifiers, and filenames."""
        return operations.keyword_search(
            keyword,
            max_results,
            collection,
            path_prefix=path_prefix,
            extensions=extensions,
            since=since,
        )

    @mcp.tool()
    def search_hybrid(
        query: str,
        top_k: int = 10,
        collection: str | None = None,
        path_prefix: list[str] | None = None,
        extensions: list[str] | None = None,
        since: str | None = None,
    ) -> str:
        """Combined semantic + keyword search. Use as fallback if `search` fails."""
        return operations.search_hybrid(
            query,
            top_k,
            collection,
            path_prefix=path_prefix,
            extensions=extensions,
            since=since,
        )

    @mcp.tool()
    def get_document(path: str, collection: str | None = None) -> str:
        """Retrieve full content of a document. Set `collection` to disambiguate."""
        return operations.get_document(path, collection)

    @mcp.tool()
    def list_documents(
        folder: str | None = None,
        limit: int = 50,
        collection: str | None = None,
        path_prefix: list[str] | None = None,
        extensions: list[str] | None = None,
        since: str | None = None,
    ) -> str:
        """List available documents. Set `collection` to filter by knowledge base."""
        return operations.list_documents(
            folder,
            limit,
            collection,
            path_prefix=path_prefix,
            extensions=extensions,
            since=since,
        )

    @mcp.tool()
    def index_stats(collection: str | None = None) -> str:
        """Get statistics about search indexes. Set `collection` for a specific one."""
        return operations.index_stats(collection)

    @mcp.tool()
    def reindex(collection: str | None = None, force: bool = False) -> str:
        """Update search indexes after adding or changing documents."""
        return operations.reindex(collection, force=force)

    @mcp.tool()
    def doctor(
        sample_query: str | None = None,
        collection: str | None = None,
    ) -> str:
        """Diagnose Trace configuration, corpus visibility, index health, and queries."""
        return operations.doctor(sample_query=sample_query, collection=collection)

    return mcp, {
        "search": search,
        "semantic_search": semantic_search,
        "keyword_search": keyword_search,
        "search_hybrid": search_hybrid,
        "get_document": get_document,
        "list_documents": list_documents,
        "index_stats": index_stats,
        "reindex": reindex,
        "doctor": doctor,
    }
