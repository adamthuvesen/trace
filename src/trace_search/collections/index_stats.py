"""Index statistics rendering helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from trace_search.config import Settings, get_settings


def _chunk_mode(chunking: dict[str, Any]) -> str:
    size = chunking.get("char_chunk_size", "unknown")
    return f"character-based (max {size} chars)"


def _overlap_info(chunking: dict[str, Any]) -> str:
    size = chunking.get("char_overlap_size", 0)
    if not size:
        return "disabled"
    return f"enabled ({size} chars)"


def render_index_stats(
    collection_stats: list[tuple[str, dict[str, object]]],
    cache_stats: Mapping[str, object],
    config: Settings | None = None,
) -> str:
    """Render index statistics for one or more collections."""
    config = config or get_settings()
    sections = []
    for name, stats in collection_stats:
        chunking = stats.get("chunking", {})
        if not isinstance(chunking, dict):
            chunking = {}

        sections.append(f"""## Collection: {name}

- **Knowledge base:** `{stats["kb_path"]}`
- **Documents:** {stats["documents"]}
- **Chunks:** {stats["total_chunks"]}
- **Generation:** {stats["generation"]}
- **Embedding model:** {stats.get("embedding_model", "unknown")} (dims={stats.get("embedding_dims", "unknown")}, backend={stats.get("embedding_backend", "unknown")})
- **Chunking:** {_chunk_mode(chunking)}, overlap {_overlap_info(chunking)}
- **Index root:** `{stats["index_root"]}`""")

    return f"""# Index Statistics

{chr(10).join(sections)}

## Shared
- **Requested embedding model:** {config.embedding_model} (dims={config.embedding_dims})
- **Cache:** {cache_stats["cache_size"]}/{cache_stats["cache_maxsize"]} (hit rate: {cache_stats["cache_hit_rate"]})
"""
