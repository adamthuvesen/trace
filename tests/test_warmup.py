"""Tests for startup embedding warmup behavior."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tests.test_runtime_hardening import FakeBackend
from trace_search.collections.collection_registry import CollectionRegistry
from trace_search.retrieval.search import SemanticSearch
from trace_search.server.server_warmup import warm_embedding_model


class RecordingBackend(FakeBackend):
    def __init__(self) -> None:
        super().__init__()
        self.encoded_batches: list[list[str]] = []

    def encode(self, texts: list[str]):
        self.encoded_batches.append(list(texts))
        return super().encode(texts)


@pytest.fixture(autouse=True)
def _reset_semantic_cache():
    SemanticSearch._embedding_cache.clear()
    SemanticSearch._cache_hits = 0
    SemanticSearch._cache_misses = 0
    yield
    SemanticSearch._embedding_cache.clear()
    SemanticSearch._cache_hits = 0
    SemanticSearch._cache_misses = 0


def test_registry_warms_backend_on_first_load(tmp_path: Path, monkeypatch):
    backend = RecordingBackend()
    monkeypatch.setattr(
        "trace_search.collections.collection_registry.build_embedding_backend",
        lambda: backend,
    )
    registry = CollectionRegistry({"fixture": tmp_path})

    assert registry.backend is backend
    assert len(backend.encoded_batches) == 1


def test_registry_warms_backend_exactly_once(tmp_path: Path, monkeypatch):
    backend = RecordingBackend()
    monkeypatch.setattr(
        "trace_search.collections.collection_registry.build_embedding_backend",
        lambda: backend,
    )
    registry = CollectionRegistry({"fixture": tmp_path})

    assert registry.backend is registry.backend
    assert registry.backend is backend
    assert len(backend.encoded_batches) == 1


def test_warmup_does_not_populate_query_cache():
    warm_embedding_model(RecordingBackend())

    assert SemanticSearch.get_cache_stats()["cache_size"] == 0
    assert SemanticSearch._cache_hits == 0
    assert SemanticSearch._cache_misses == 0


def test_warmup_input_still_cache_misses_as_user_query():
    backend = RecordingBackend()
    semantic = SemanticSearch(MagicMock(), backend)
    warm_embedding_model(backend)

    before_misses = SemanticSearch._cache_misses
    semantic._get_query_embedding("hello world")

    assert SemanticSearch._cache_misses == before_misses + 1
