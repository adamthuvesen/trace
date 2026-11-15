"""Typed entry points for fakes that tests pass where production code expects a real type."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from pydantic_settings import SettingsConfigDict

from trace_search.config import Settings
from trace_search.indexing.wiki_indexer import WikiIndexer
from trace_search.server.cli import OperationsFactory


class _DotenvFreeSettings(Settings):
    model_config = SettingsConfigDict(env_file=None)


def settings_without_dotenv(**values: Any) -> Settings:
    """Build `Settings` that ignore any `.env` file in the working directory."""
    return _DotenvFreeSettings(**values)


def fake_indexer(**attributes: Any) -> WikiIndexer:
    """Stand in for the few `WikiIndexer` attributes a search class reads."""
    return cast(WikiIndexer, SimpleNamespace(**attributes))


def fake_operations_factory(factory: object) -> OperationsFactory:
    """Pass a fake operations class or factory to `run_cli`."""
    return cast(OperationsFactory, factory)
