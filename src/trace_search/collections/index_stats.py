"""Index statistics rendering helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from trace_search.config import settings


def _chunk_mode(chunking: dict[str, Any]) -> str:
    size = chunking.get("char_chunk_size", settings.char_chunk_size)
    return f"character-based (max {size} chars)"


def _overlap_info(chunking: dict[str, Any]) -> str:
    if not chunking.get("enable_overlap"):
        return "disabled"
    size = chunking.get("char_overlap_size", settings.char_overlap_size)
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
- **ChromaDB chunks:** {stats["total_chunks"]}
- **BM25 documents:** {stats["bm25_docs"]}
- **BM25 available:** {stats["bm25_available"]}
- **Chunking:** {_chunk_mode(chunking)}, overlap {_overlap_info(chunking)}
- **ChromaDB path:** `{stats["chroma_path"]}`
- **BM25 path:** `{stats["bm25_path"]}`""")

    return f"""# Index Statistics

{chr(10).join(sections)}

## Shared
- **Embedding model:** {settings.embedding_model} (dims={settings.embedding_dims})
- **Embedding backend:** {settings.embedding_backend}
- **Reranker:** {settings.reranker_model} (enabled={settings.reranker_enabled})
- **Cache:** {cache_stats["cache_size"]}/{cache_stats["cache_maxsize"]} (hit rate: {cache_stats["cache_hit_rate"]})
"""
