"""Tests for the embedding backend abstraction."""

from __future__ import annotations

import numpy as np
import pytest

from trace_search.config import get_settings
from trace_search.embeddings import (
    EmbeddingBackend,
    OnnxBackend,
    TorchBackend,
    build_embedding_backend,
)


@pytest.fixture(autouse=True)
def _reset_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.slow
def test_torch_backend_satisfies_protocol():
    backend = TorchBackend("all-MiniLM-L6-v2")
    assert isinstance(backend, EmbeddingBackend)
    assert backend.model_name == "all-MiniLM-L6-v2"
    assert backend.dim == 384


@pytest.mark.slow
def test_onnx_backend_satisfies_protocol():
    backend = OnnxBackend("all-MiniLM-L6-v2")
    assert isinstance(backend, EmbeddingBackend)
    assert backend.model_name == "all-MiniLM-L6-v2"
    assert backend.dim == 384


@pytest.mark.slow
def test_encode_shape_and_dtype():
    for backend in (TorchBackend("all-MiniLM-L6-v2"), OnnxBackend("all-MiniLM-L6-v2")):
        out = backend.encode(["hello world", "second sentence"])
        assert out.shape == (2, 384)
        assert out.dtype == np.float32


@pytest.mark.slow
def test_encode_one_shape_and_dtype():
    for backend in (TorchBackend("all-MiniLM-L6-v2"), OnnxBackend("all-MiniLM-L6-v2")):
        out = backend.encode_one("hello world")
        assert out.shape == (384,)
        assert out.dtype == np.float32


@pytest.mark.slow
def test_factory_returns_torch(monkeypatch):
    monkeypatch.setenv("EMBEDDING_BACKEND", "torch")
    get_settings.cache_clear()
    backend = build_embedding_backend()
    assert isinstance(backend, TorchBackend)


@pytest.mark.slow
def test_factory_returns_onnx(monkeypatch):
    monkeypatch.setenv("EMBEDDING_BACKEND", "onnx")
    get_settings.cache_clear()
    backend = build_embedding_backend()
    assert isinstance(backend, OnnxBackend)


def test_invalid_backend_value_raises(monkeypatch):
    monkeypatch.setenv("EMBEDDING_BACKEND", "mps")
    get_settings.cache_clear()
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        # Trigger settings construction via any attribute read on the fresh cache
        from trace_search.config import Settings

        Settings()


def test_eval_cli_has_ab_flag():
    """Smoke test: --ab flag is registered on the eval CLI."""
    from tools.eval.cli import main

    param_names = {p.name for p in main.params}
    assert "ab" in param_names
    for name in (
        "ci_stress",
        "include_stress",
        "stress",
        "strict_keywords",
        "strict_keywords_top1",
    ):
        assert name in param_names
