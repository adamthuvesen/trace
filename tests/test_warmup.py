"""Tests for startup embedding warmup behavior."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from trace_search.config import get_settings
from trace_search.search import SemanticSearch
from trace_search.server_app import CollectionRegistry


FIXTURE_KB = Path(__file__).parent.parent / "tools" / "eval" / "fixture_kb"


@pytest.fixture(autouse=True)
def _reset_settings_and_cache(monkeypatch):
    """Reset cached settings and the class-level semantic cache between tests."""
    get_settings.cache_clear()
    SemanticSearch._embedding_cache.clear()
    SemanticSearch._cache_hits = 0
    SemanticSearch._cache_misses = 0
    yield
    get_settings.cache_clear()
    SemanticSearch._embedding_cache.clear()
    SemanticSearch._cache_hits = 0
    SemanticSearch._cache_misses = 0


def _registry(tmp_path: Path) -> CollectionRegistry:
    if not FIXTURE_KB.exists():
        pytest.skip("fixture_kb missing; skip KB-backed warmup test")
    return CollectionRegistry({"fixture": FIXTURE_KB}, index_root=tmp_path)


@pytest.mark.slow
def test_warmup_runs_when_enabled(tmp_path, caplog, monkeypatch):
    monkeypatch.setenv("EMBEDDING_WARMUP_ENABLED", "true")
    get_settings.cache_clear()

    caplog.set_level(logging.INFO, logger="trace_search.server_app")
    reg = _registry(tmp_path)
    _ = reg.backend  # trigger lazy load + warmup

    messages = [r.getMessage() for r in caplog.records]
    assert any("Embedding model warmed" in m for m in messages)


@pytest.mark.slow
def test_warmup_runs_exactly_once(tmp_path, caplog, monkeypatch):
    monkeypatch.setenv("EMBEDDING_WARMUP_ENABLED", "true")
    get_settings.cache_clear()

    caplog.set_level(logging.INFO, logger="trace_search.server_app")
    reg = _registry(tmp_path)
    _ = reg.backend
    _ = reg.backend
    _ = reg.backend

    warmup_lines = [
        r for r in caplog.records if "Embedding model warmed" in r.getMessage()
    ]
    assert len(warmup_lines) == 1


@pytest.mark.slow
def test_warmup_skipped_when_disabled(tmp_path, caplog, monkeypatch):
    monkeypatch.setenv("EMBEDDING_WARMUP_ENABLED", "false")
    get_settings.cache_clear()

    caplog.set_level(logging.INFO, logger="trace_search.server_app")
    reg = _registry(tmp_path)
    _ = reg.backend

    messages = [r.getMessage() for r in caplog.records]
    assert not any("Embedding model warmed" in m for m in messages)


@pytest.mark.slow
def test_warmup_does_not_populate_query_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("EMBEDDING_WARMUP_ENABLED", "true")
    get_settings.cache_clear()

    reg = _registry(tmp_path)
    _ = reg.backend

    assert len(SemanticSearch._embedding_cache) == 0
    assert SemanticSearch._cache_hits == 0
    assert SemanticSearch._cache_misses == 0


@pytest.mark.slow
def test_warmup_input_still_cache_misses_as_user_query(tmp_path, monkeypatch):
    """Warmup must not make a subsequent real query look like a cache hit."""
    monkeypatch.setenv("EMBEDDING_WARMUP_ENABLED", "true")
    get_settings.cache_clear()

    reg = _registry(tmp_path)
    col = reg.collections["fixture"]
    semantic = col.get_semantic(reg.backend)

    before_misses = SemanticSearch._cache_misses
    # "hello world" is one of the warmup sentences
    semantic._get_query_embedding("hello world")
    assert SemanticSearch._cache_misses == before_misses + 1
