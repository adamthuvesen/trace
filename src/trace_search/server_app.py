"""MCP server entrypoints and backward-compatible re-exports."""

from __future__ import annotations

from trace_search.collection_registry import Collection, CollectionRegistry
from trace_search.mcp_tools import _build_multi_instructions, build_multi_mcp
from trace_search.server_warmup import warm_embedding_model

__all__ = [
    "Collection",
    "CollectionRegistry",
    "build_multi_mcp",
    "warm_embedding_model",
    "_build_multi_instructions",
]
