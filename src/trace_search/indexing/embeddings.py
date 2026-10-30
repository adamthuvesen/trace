"""Embedding backend: ONNX int8 models via fastembed."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray

from trace_search.config import MODEL_SPECS, Settings, get_settings

logger = logging.getLogger(__name__)


def model_cache_dir() -> Path:
    """Persistent cache for downloaded embedding models.

    fastembed defaults to the system temp directory. macOS purges `$TMPDIR`, and
    on 2026-08-05 it had deleted the blobs while leaving the snapshot symlinks
    behind, so every search failed with
    `NO_SUCHFILE: Load model ... model.onnx failed`. Nothing surfaced it —
    `trace reindex` still exited 0, so the index looked healthy while retrieval
    was dead. A model download is expensive and long-lived; a temp directory is
    the wrong home for it.

    Override with `TRACE_MODEL_CACHE`.
    """
    override = os.environ.get("TRACE_MODEL_CACHE")
    if override:
        path = Path(override).expanduser()
    else:
        base = os.environ.get("XDG_CACHE_HOME")
        root = Path(base).expanduser() if base else Path.home() / ".cache"
        path = root / "trace" / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


type EmbeddingArray = NDArray[np.float32]


@runtime_checkable
class EmbeddingBackend(Protocol):
    """Common interface for embedding runtimes.

    Implementations MUST return `np.float32` arrays. `encode` produces a 2-D
    array shaped `(len(texts), dim)`; `encode_one` produces a 1-D `(dim,)`.
    """

    model_name: str
    dim: int

    def encode(self, texts: list[str]) -> EmbeddingArray: ...
    def encode_one(self, text: str) -> EmbeddingArray: ...


# ONNX Runtime keeps the arena it grows for the largest batch, so a big batch
# during a full rebuild pins memory in a long-lived server: embedding a 3,200-chunk wiki
# peaked at 2.4 GB with fastembed's default of 256 and 0.4 GB with 16, at the
# same speed.
_EMBED_BATCH_SIZE = 16


class OnnxBackend:
    """Backend wrapping `fastembed.TextEmbedding` (pre-quantized ONNX int8)."""

    def __init__(self, model_name: str):
        # The HF tokenizer warns and disables itself when the process forks
        # after first use; say up front that it runs single-threaded.
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        from fastembed import TextEmbedding

        if model_name not in MODEL_SPECS:
            raise ValueError(
                f"Model '{model_name}' is not supported. Supported: {list(MODEL_SPECS)}."
            )
        self.model_name = model_name
        self._model = TextEmbedding(
            model_name=MODEL_SPECS[model_name].runtime_identifier,
            cache_dir=str(model_cache_dir()),
        )
        probe = next(iter(self._model.embed(["probe"])))
        self.dim = int(np.asarray(probe).shape[-1])

    def encode(self, texts: list[str]) -> EmbeddingArray:
        if not texts:
            return np.empty((0, self.dim), dtype=np.float32)
        vectors = list(self._model.embed(list(texts), batch_size=_EMBED_BATCH_SIZE))
        return np.asarray(np.stack(vectors), dtype=np.float32)

    def encode_one(self, text: str) -> EmbeddingArray:
        return np.asarray(self.encode([text])[0], dtype=np.float32)


def build_embedding_backend(config: Settings | None = None) -> EmbeddingBackend:
    """Construct the ONNX embedding backend for `settings.embedding_model`."""
    impl = OnnxBackend((config or get_settings()).embedding_model)
    logger.info("Embedding backend: onnx (model=%s, dim=%d)", impl.model_name, impl.dim)
    return impl
