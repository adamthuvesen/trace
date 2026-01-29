"""Embedding backend abstraction (torch via SentenceTransformer, ONNX via fastembed)."""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

import numpy as np

from trace_search.config import settings

logger = logging.getLogger(__name__)


@runtime_checkable
class EmbeddingBackend(Protocol):
    """Common interface for embedding runtimes.

    Implementations MUST return `np.float32` arrays. `encode` produces a 2-D
    array shaped `(len(texts), dim)`; `encode_one` produces a 1-D `(dim,)`.
    """

    model_name: str
    dim: int

    def encode(self, texts: list[str]) -> np.ndarray: ...
    def encode_one(self, text: str) -> np.ndarray: ...


class TorchBackend:
    """Backend wrapping `sentence_transformers.SentenceTransformer`."""

    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self._model = SentenceTransformer(model_name)
        # Resolve dim from a one-shot probe; `get_sentence_embedding_dimension`
        # is available but probing avoids coupling to that API.
        probe = self._model.encode(["probe"])
        self.dim = int(np.asarray(probe).shape[-1])

    def encode(self, texts: list[str]) -> np.ndarray:
        vectors = self._model.encode(texts)
        return np.asarray(vectors, dtype=np.float32)

    def encode_one(self, text: str) -> np.ndarray:
        return self.encode([text])[0]


# fastembed uses HF-prefixed names; map our canonical keys to its identifiers.
_FASTEMBED_MODEL_MAP: dict[str, str] = {
    "all-MiniLM-L6-v2": "sentence-transformers/all-MiniLM-L6-v2",
    "BAAI/bge-base-en-v1.5": "BAAI/bge-base-en-v1.5",
}


class OnnxBackend:
    """Backend wrapping `fastembed.TextEmbedding` (pre-quantized ONNX int8)."""

    def __init__(self, model_name: str):
        from fastembed import TextEmbedding

        if model_name not in _FASTEMBED_MODEL_MAP:
            raise ValueError(
                f"Model '{model_name}' not supported by the ONNX backend. "
                f"Supported: {list(_FASTEMBED_MODEL_MAP)}. "
                "Set EMBEDDING_BACKEND=torch to use this model."
            )
        self.model_name = model_name
        self._model = TextEmbedding(model_name=_FASTEMBED_MODEL_MAP[model_name])
        probe = next(iter(self._model.embed(["probe"])))
        self.dim = int(np.asarray(probe).shape[-1])

    def encode(self, texts: list[str]) -> np.ndarray:
        vectors = list(self._model.embed(list(texts)))
        return np.asarray(np.stack(vectors), dtype=np.float32)

    def encode_one(self, text: str) -> np.ndarray:
        return self.encode([text])[0]


def build_embedding_backend() -> EmbeddingBackend:
    """Construct the embedding backend named by `settings.embedding_backend`."""
    backend = settings.embedding_backend
    model = settings.embedding_model
    if backend == "torch":
        impl: EmbeddingBackend = TorchBackend(model)
    elif backend == "onnx":
        impl = OnnxBackend(model)
    else:
        # Settings validator should catch this; guard defensively.
        raise ValueError(
            f"Unknown embedding backend '{backend}'. Expected 'torch' or 'onnx'."
        )
    logger.info(
        "Embedding backend: %s (model=%s, dim=%d)", backend, impl.model_name, impl.dim
    )
    return impl
