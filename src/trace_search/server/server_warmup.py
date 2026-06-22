"""Embedding model warmup for server startup."""

from __future__ import annotations

import logging
import time

from trace_search.indexing.embeddings import EmbeddingBackend

logger = logging.getLogger(__name__)

_WARMUP_SENTENCES: tuple[str, ...] = (
    "x",
    "hello world",
    "what is an acronym",
    "how do we document recurring service reviews at the end of a cycle",
    "the quick brown fox jumps over the lazy dog while indexing knowledge bases",
)


def warm_embedding_model(backend: EmbeddingBackend) -> float | None:
    """Run a short encode pass to warm embedding kernels. Returns elapsed ms."""
    start = time.perf_counter()
    backend.encode(list(_WARMUP_SENTENCES))
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info("Embedding model warmed in %.1f ms", elapsed_ms)
    return elapsed_ms
