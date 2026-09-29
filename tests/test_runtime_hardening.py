"""Regression tests for runtime reliability and deterministic behavior."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from trace_search.indexing.kb_paths import should_exclude_path
from trace_search.indexing.wiki_indexer import WikiIndexer
from trace_search.retrieval.search import KeywordSearch


class FakeBackend:
    """Minimal `EmbeddingBackend` stand-in for indexing path tests."""

    def __init__(self, model_name: str = "fake") -> None:
        self.model_name = model_name
        self.dim = 3

    def encode(self, texts: list[str]):
        arr = np.asarray(
            [[float(i), 0.0, 0.0] for i, _ in enumerate(texts)], dtype=np.float32
        )
        return arr

    def encode_one(self, text: str):
        return self.encode([text])[0]


def test_package_import_without_kb_path_succeeds():
    """Package import should not fail immediately when KB_PATH is unset."""
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.pop("KB_PATH", None)
    env["PYTHONPATH"] = str(repo_root / "src") + os.pathsep + env.get("PYTHONPATH", "")

    proc = subprocess.run(
        [sys.executable, "-c", "import trace_search"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr


def test_settings_allow_non_kb_access_without_kb_path(monkeypatch):
    """Non-KB settings should be readable even without KB_PATH."""
    from trace_search.config import get_settings, settings

    monkeypatch.delenv("KB_PATH", raising=False)
    get_settings.cache_clear()
    try:
        assert settings.embedding_model == "all-MiniLM-L6-v2"
        assert settings.bm25_k1 == 1.2
    finally:
        get_settings.cache_clear()


def test_settings_reject_invalid_log_level():
    from trace_search.config import Settings

    with pytest.raises(ValueError, match="Invalid LOG_LEVEL"):
        Settings(log_level="chatty")


def test_settings_normalize_valid_log_level():
    from trace_search.config import Settings

    assert Settings(log_level="debug").log_level == "DEBUG"
    assert Settings(log_level="notset").log_level == "NOTSET"


def test_settings_load_kb_path_from_dotenv(tmp_path, monkeypatch):
    """Local .env files should be honored for teammate-friendly setup."""
    from trace_search.config import get_settings

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (tmp_path / ".env").write_text(f"KB_PATH={docs_dir}\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("KB_PATH", raising=False)
    get_settings.cache_clear()
    try:
        assert get_settings().resolved_kb_path == docs_dir
    finally:
        get_settings.cache_clear()


def test_runtime_requires_kb_path(monkeypatch):
    """Indexer runtime should fail with clear error if KB_PATH is missing."""
    from trace_search.config import get_settings

    monkeypatch.delenv("KB_PATH", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(ValueError, match="KB_PATH is required"):
            WikiIndexer()
    finally:
        get_settings.cache_clear()


def test_default_indexes_live_under_mcp_search_indexes(tmp_path, monkeypatch):
    """Direct WikiIndexer defaults should match documented server index layout."""
    from trace_search.config import get_settings

    monkeypatch.setenv("KB_PATH", str(tmp_path))
    get_settings.cache_clear()

    try:
        indexer = WikiIndexer(backend=FakeBackend())
    finally:
        get_settings.cache_clear()

    expected_root = tmp_path / ".mcp-search" / "indexes"
    assert indexer.index_root == expected_root


def test_force_rebuild_after_all_docs_removed_publishes_empty_index(tmp_path):
    """Deleting every doc and force-rebuilding must not keep serving stale chunks."""

    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "stale.md").write_text("# Stale\n\nstale widget notes", encoding="utf-8")
    indexer = WikiIndexer(kb, index_root=tmp_path / "idx", backend=FakeBackend())
    assert indexer.build_index(force=True) == 1

    (kb / "stale.md").unlink()

    assert indexer.build_index(force=True) == 0
    assert len(indexer.snapshot()) == 0
    assert KeywordSearch(indexer).search("widget") == []


def test_load_documents_is_deterministic(tmp_path, monkeypatch):
    """load_documents should return documents in stable path order."""
    from trace_search.config import get_settings

    (tmp_path / "b").mkdir()
    (tmp_path / "a").mkdir()
    (tmp_path / "b" / "z.md").write_text("# Z\n\ncontent", encoding="utf-8")
    (tmp_path / "a" / "a.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "a" / "m.md").write_text("# M\n\ncontent", encoding="utf-8")

    monkeypatch.setenv("KB_PATH", str(tmp_path))
    get_settings.cache_clear()

    try:
        indexer = WikiIndexer(backend=FakeBackend())
        docs = indexer.load_documents()
    finally:
        get_settings.cache_clear()

    paths = [doc["path"] for doc in docs]
    assert paths == sorted(paths)


def test_load_documents_allows_hidden_parent_dirs(tmp_path, monkeypatch):
    """Hidden ancestors outside the KB root should not exclude valid documents."""
    from trace_search.config import get_settings

    kb = tmp_path / ".mirror" / "docs"
    kb.mkdir(parents=True)
    (kb / "intro.md").write_text("# Intro\n\ncontent", encoding="utf-8")

    monkeypatch.setenv("KB_PATH", str(kb))
    get_settings.cache_clear()

    try:
        indexer = WikiIndexer(backend=FakeBackend())
        docs = indexer.load_documents()
    finally:
        get_settings.cache_clear()

    assert [doc["path"] for doc in docs] == ["intro.md"]


def test_load_documents_single_rglob_walk(tmp_path, monkeypatch):
    """load_documents should traverse the KB with exactly one rglob('*') call."""
    from unittest.mock import patch
    from trace_search.config import get_settings

    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "intro.md").write_text("# Intro\n\ncontent", encoding="utf-8")
    (tmp_path / "docs" / "query.sql").write_text("SELECT 1;", encoding="utf-8")

    monkeypatch.setenv("KB_PATH", str(tmp_path))
    get_settings.cache_clear()

    rglob_calls = []
    original_rglob = Path.rglob

    def spy_rglob(self, pattern):
        rglob_calls.append(pattern)
        return original_rglob(self, pattern)

    try:
        indexer = WikiIndexer(backend=FakeBackend())
        with patch.object(Path, "rglob", spy_rglob):
            docs = indexer.load_documents()
    finally:
        get_settings.cache_clear()

    assert rglob_calls == ["*"], (
        f"Expected exactly one rglob('*') call, got: {rglob_calls}"
    )
    paths = [d["path"] for d in docs]
    assert paths == sorted(paths)


class TestExcludePatternMatching:
    def test_nested_node_modules_is_excluded(self, tmp_path):
        """node_modules directory nested under KB root should be excluded."""
        p = tmp_path / "project" / "node_modules" / "foo.md"
        assert should_exclude_path(p, tmp_path)

    def test_substring_lookalike_is_not_excluded(self, tmp_path):
        """A file whose name contains an exclude token as a substring is not excluded."""
        p = tmp_path / "notes" / "my_node_modules_writeup.md"
        assert not should_exclude_path(p, tmp_path)

    def test_kb_rooted_under_git_mirror_not_excluded(self, tmp_path):
        """A KB rooted under a path that contains .git in a parent segment is not excluded."""
        mirror = tmp_path / ".git-mirror" / "docs"
        mirror.mkdir(parents=True)
        assert not should_exclude_path(mirror / "intro.md", mirror)

    def test_hidden_dir_within_kb_excluded_by_leading_dot(self, tmp_path):
        """A file inside a .hidden dir is excluded because the part starts with '.'."""
        p = tmp_path / ".venv" / "lib" / "site.py"
        assert should_exclude_path(p, tmp_path)

    def test_hidden_parent_outside_kb_is_not_excluded(self, tmp_path):
        """Only KB-relative hidden parts should be excluded."""
        kb = tmp_path / ".mirror" / "docs"
        kb.mkdir(parents=True)
        assert not should_exclude_path(kb / "intro.md", kb)

    def test_symlink_to_outside_kb_is_excluded(self, tmp_path):
        """Resolved paths must stay inside the KB root."""
        kb = tmp_path / "kb"
        outside = tmp_path / "outside"
        kb.mkdir()
        outside.mkdir()
        target = outside / "secret.md"
        target.write_text("# Secret\n\nDo not index", encoding="utf-8")
        link = kb / "secret-link.md"
        link.symlink_to(target)

        assert should_exclude_path(link, kb)

    def test_load_documents_skips_outside_symlink_but_keeps_inside_symlink(
        self, tmp_path, monkeypatch
    ):
        from trace_search.config import get_settings

        kb = tmp_path / "kb"
        outside = tmp_path / "outside"
        kb.mkdir()
        outside.mkdir()
        (kb / "real.md").write_text("# Real\n\nInside", encoding="utf-8")
        (outside / "secret.md").write_text("# Secret\n\nOutside", encoding="utf-8")
        (kb / "inside-link.md").symlink_to(kb / "real.md")
        (kb / "outside-link.md").symlink_to(outside / "secret.md")

        monkeypatch.setenv("KB_PATH", str(kb))
        get_settings.cache_clear()
        try:
            indexer = WikiIndexer(backend=FakeBackend())
            docs = indexer.load_documents()
        finally:
            get_settings.cache_clear()

        paths = {doc["path"] for doc in docs}
        assert "real.md" in paths
        assert "inside-link.md" in paths
        assert "outside-link.md" not in paths
