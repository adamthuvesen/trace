"""Shared test fixtures and configuration."""

from pathlib import Path

import pytest


@pytest.fixture
def wiki_path() -> Path:
    """Path to wiki knowledge base when KB-backed tests are configured."""
    from trace_search.config import get_settings, settings

    get_settings.cache_clear()
    try:
        try:
            kb_path = settings.resolved_kb_path
        except ValueError as exc:
            pytest.skip(f"KB-backed test requires KB_PATH: {exc}")

        yield kb_path
    finally:
        get_settings.cache_clear()
