"""Index statistics rendering helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from trace_search.config import settings


def _chunk_mode(chunking: dict[str, Any]) -> str:
    size = chunking.get("char_chunk_size", settings.char_chunk_size)
    return f"character-based (max {size} chars)"


def _overlap_info(chunking: dict[str, Any]) -> str:
    size = chunking.get("char_overlap_size", settings.char_overlap_size)
    if not size:
        return "disabled"
    return f"enabled ({size} chars)"


def render_index_stats(
    collection_stats: list[tuple[str, dict[str, object]]],
    cache_stats: Mapping[str, object],
) -> str:
    """Render index statistics for one or more collections."""
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
- **Chunking:** {_chunk_mode(chunking)}, overlap {_overlap_info(chunking)}
- **Index root:** `{stats["index_root"]}`""")

    return f"""# Index Statistics

{chr(10).join(sections)}

## Shared
- **Embedding model:** {settings.embedding_model} (dims={settings.embedding_dims})
- **Cache:** {cache_stats["cache_size"]}/{cache_stats["cache_maxsize"]} (hit rate: {cache_stats["cache_hit_rate"]})
"""
