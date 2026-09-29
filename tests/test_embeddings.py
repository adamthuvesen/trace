"""Tests for the embedding backend."""

from __future__ import annotations

import numpy as np
import pytest

from trace_search.config import get_settings
from trace_search.indexing.embeddings import (
    EmbeddingBackend,
    OnnxBackend,
    build_embedding_backend,
)


@pytest.fixture(autouse=True)
def _reset_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.slow
def test_onnx_backend_satisfies_protocol():
    backend = OnnxBackend("all-MiniLM-L6-v2")
    assert isinstance(backend, EmbeddingBackend)
    assert backend.model_name == "all-MiniLM-L6-v2"
    assert backend.dim == 384


@pytest.mark.slow
def test_encode_shape_and_dtype():
    backend = OnnxBackend("all-MiniLM-L6-v2")
    assert backend.encode(["hello world", "second sentence"]).shape == (2, 384)
    out = backend.encode_one("hello world")
    assert out.shape == (384,)
    assert out.dtype == np.float32


@pytest.mark.slow
def test_factory_returns_onnx():
    assert isinstance(build_embedding_backend(), OnnxBackend)


def test_unsupported_model_is_rejected_before_loading():
    with pytest.raises(ValueError, match="not supported"):
        OnnxBackend("no-such-model")


def test_empty_encode_returns_empty_matrix():
    backend = OnnxBackend.__new__(OnnxBackend)
    backend.dim = 384
    out = backend.encode([])
    assert out.shape == (0, 384)
    assert out.dtype == np.float32


def test_eval_cli_registers_stress_and_keyword_flags():
    from tools.eval.cli import main

    param_names = {p.name for p in main.params}
    for name in (
        "ci_stress",
        "include_stress",
        "stress",
        "strict_keywords",
        "strict_keywords_top1",
    ):
        assert name in param_names
