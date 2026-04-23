"""Regression tests for runtime reliability and deterministic behavior."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


class FakeEmbeddings(list):
    """List-like embedding container with numpy-like tolist support."""

    def __getitem__(self, key):
        value = super().__getitem__(key)
        if isinstance(key, slice):
            return FakeEmbeddings(value)
        return value

    def tolist(self) -> list:
        return list(self)


class FakeCollection:
    """In-memory Chroma collection for deterministic tests."""

    def __init__(self) -> None:
        self._rows: dict[str, dict] = {}

    def count(self) -> int:
        return len(self._rows)

    def get(self) -> dict[str, list[str]]:
        return {"ids": list(self._rows.keys())}

    def delete(self, ids: list[str]) -> None:
        for doc_id in ids:
            self._rows.pop(doc_id, None)

    def add(
        self,
        *,
        ids: list[str],
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
    ) -> None:
        for i, doc_id in enumerate(ids):
            if doc_id in self._rows:
                raise ValueError(f"duplicate id: {doc_id}")
            self._rows[doc_id] = {
                "document": documents[i],
                "embedding": embeddings[i],
                "metadata": metadatas[i],
            }


class FakeChromaClient:
    """Minimal stand-in for chromadb.PersistentClient."""

    def __init__(self, path: str, settings) -> None:  # noqa: ARG002
        self.path = path
        self._collections: dict[str, FakeCollection] = {}

    def get_or_create_collection(
        self,
        name: str,
        metadata: dict | None = None,  # noqa: ARG002
    ) -> FakeCollection:
        if name not in self._collections:
            self._collections[name] = FakeCollection()
        return self._collections[name]

    def delete_collection(self, name: str) -> None:
        self._collections.pop(name, None)


class FakeBackend:
    """Minimal `EmbeddingBackend` stand-in for indexing path tests."""

    def __init__(self, model_name: str = "fake") -> None:
        self.model_name = model_name
        self.dim = 3

    def encode(self, texts: list[str]) -> FakeEmbeddings:
        import numpy as np

        arr = np.asarray(
            [[float(i), 0.0, 0.0] for i, _ in enumerate(texts)], dtype=np.float32
        )
        return arr

    def encode_one(self, text: str):
        return self.encode([text])[0]


class FakeBM25:
    """Minimal BM25 stand-in for indexing path tests."""

    def __init__(self, k1: float = 1.2, b: float = 0.5) -> None:
        self.k1 = k1
        self.b = b

    def index(self, corpus_tokens: list[str]) -> None:  # noqa: ARG002
        return None

    def save(self, path: str, corpus: list[str] | None = None) -> None:  # noqa: ARG002
        out = Path(path)
        out.mkdir(parents=True, exist_ok=True)
        (out / "bm25.fake").write_text("ok", encoding="utf-8")

    @classmethod
    def load(cls, path: str, load_corpus: bool = True):  # noqa: ARG003
        if not Path(path).exists():
            raise FileNotFoundError(path)
        return cls()


@pytest.fixture
def patched_indexer_runtime(monkeypatch):
    """Patch heavy indexer dependencies with lightweight fakes."""
    import trace_search.indexer as indexer_module

    monkeypatch.setattr(indexer_module.chromadb, "PersistentClient", FakeChromaClient)
    monkeypatch.setattr(
        indexer_module,
        "build_embedding_backend",
        lambda: FakeBackend(),
    )
    monkeypatch.setattr(indexer_module.bm25s, "tokenize", lambda texts, **kwargs: texts)
    monkeypatch.setattr(indexer_module.bm25s, "BM25", FakeBM25)
    return indexer_module


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
    from trace_search.indexer import WikiIndexer

    monkeypatch.delenv("KB_PATH", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(ValueError, match="KB_PATH is required"):
            WikiIndexer()
    finally:
        get_settings.cache_clear()


def test_chroma_path_env_override_is_honored(
    tmp_path, monkeypatch, patched_indexer_runtime
):
    """CHROMA_PATH env var should override computed Chroma path."""
    from trace_search.config import get_settings

    custom_chroma = tmp_path / "custom-chroma"
    monkeypatch.setenv("KB_PATH", str(tmp_path))
    monkeypatch.setenv("CHROMA_PATH", str(custom_chroma))
    get_settings.cache_clear()

    try:
        indexer = patched_indexer_runtime.WikiIndexer()
    finally:
        get_settings.cache_clear()

    assert indexer.chroma_path == custom_chroma


def test_default_indexes_live_under_mcp_search_indexes(
    tmp_path, monkeypatch, patched_indexer_runtime
):
    """Direct WikiIndexer defaults should match documented server index layout."""
    from trace_search.config import get_settings

    monkeypatch.setenv("KB_PATH", str(tmp_path))
    get_settings.cache_clear()

    try:
        indexer = patched_indexer_runtime.WikiIndexer()
    finally:
        get_settings.cache_clear()

    expected_root = tmp_path / ".mcp-search" / "indexes"
    assert indexer.chroma_path.parent == expected_root
    assert indexer.bm25_path.parent == expected_root


def test_force_rebuild_with_empty_docs_clears_stale_indexes(
    tmp_path,
    monkeypatch,
    patched_indexer_runtime,
):
    """force=True with no docs should clear stale Chroma/BM25 state."""
    from trace_search.config import get_settings

    monkeypatch.setenv("KB_PATH", str(tmp_path))
    get_settings.cache_clear()

    try:
        indexer = patched_indexer_runtime.WikiIndexer()
        indexer.collection.add(
            ids=["stale.md::0"],
            documents=["stale"],
            embeddings=[[0.0, 0.0, 0.0]],
            metadatas=[
                {"path": "stale.md", "title": "stale", "folder": "", "chunk_index": 0}
            ],
        )
        indexer.bm25_path.mkdir(parents=True, exist_ok=True)
        (indexer.bm25_path / "metadata.json").write_text("[]", encoding="utf-8")

        monkeypatch.setattr(indexer, "load_documents", lambda: [])
        result = indexer.build_index(force=True)
    finally:
        get_settings.cache_clear()

    assert result == 0
    assert indexer.collection.count() == 0
    assert not indexer.bm25_path.exists()


def test_partial_index_state_recovers_without_duplicate_ids(
    tmp_path,
    monkeypatch,
    patched_indexer_runtime,
):
    """If only one backend exists, rebuild should reconcile cleanly."""
    from trace_search.config import get_settings

    monkeypatch.setenv("KB_PATH", str(tmp_path))
    get_settings.cache_clear()

    try:
        indexer = patched_indexer_runtime.WikiIndexer()

        # Partial state: Chroma has stale row, BM25 directory is missing.
        indexer.collection.add(
            ids=["doc.md::0"],
            documents=["stale"],
            embeddings=[[0.0, 0.0, 0.0]],
            metadatas=[
                {"path": "doc.md", "title": "Doc", "folder": "", "chunk_index": 0}
            ],
        )
        if indexer.bm25_path.exists():
            shutil.rmtree(indexer.bm25_path)

        monkeypatch.setattr(
            indexer,
            "load_documents",
            lambda: [
                {
                    "path": "doc.md",
                    "title": "Doc",
                    "folder": "",
                    "content": "# Doc\n\nCurrent content",
                    "hash": "abc",
                }
            ],
        )

        count = indexer.build_index(force=False)
    finally:
        get_settings.cache_clear()

    assert count == 1
    assert indexer.collection.count() == 1
    assert indexer.bm25_path.exists()


def test_load_documents_is_deterministic(
    tmp_path,
    monkeypatch,
    patched_indexer_runtime,
):
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
        indexer = patched_indexer_runtime.WikiIndexer()
        docs = indexer.load_documents()
    finally:
        get_settings.cache_clear()

    paths = [doc["path"] for doc in docs]
    assert paths == sorted(paths)


def test_load_documents_allows_hidden_parent_dirs(
    tmp_path,
    monkeypatch,
    patched_indexer_runtime,
):
    """Hidden ancestors outside the KB root should not exclude valid documents."""
    from trace_search.config import get_settings

    kb = tmp_path / ".mirror" / "docs"
    kb.mkdir(parents=True)
    (kb / "intro.md").write_text("# Intro\n\ncontent", encoding="utf-8")

    monkeypatch.setenv("KB_PATH", str(kb))
    get_settings.cache_clear()

    try:
        indexer = patched_indexer_runtime.WikiIndexer()
        docs = indexer.load_documents()
    finally:
        get_settings.cache_clear()

    assert [doc["path"] for doc in docs] == ["intro.md"]


def test_load_documents_single_rglob_walk(
    tmp_path, monkeypatch, patched_indexer_runtime
):
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
        indexer = patched_indexer_runtime.WikiIndexer()
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
    """Tests for WikiIndexer._should_exclude path-component matching."""

    def _make_indexer(self, kb_path, patched_indexer_runtime, monkeypatch):
        from trace_search.config import get_settings

        monkeypatch.setenv("KB_PATH", str(kb_path))
        get_settings.cache_clear()
        try:
            return patched_indexer_runtime.WikiIndexer()
        finally:
            get_settings.cache_clear()

    def test_nested_node_modules_is_excluded(
        self, tmp_path, monkeypatch, patched_indexer_runtime
    ):
        """node_modules directory nested under KB root should be excluded."""
        indexer = self._make_indexer(tmp_path, patched_indexer_runtime, monkeypatch)
        p = tmp_path / "project" / "node_modules" / "foo.md"
        assert indexer._should_exclude(p)

    def test_substring_lookalike_is_not_excluded(
        self, tmp_path, monkeypatch, patched_indexer_runtime
    ):
        """A file whose name contains an exclude token as a substring is not excluded."""
        indexer = self._make_indexer(tmp_path, patched_indexer_runtime, monkeypatch)
        p = tmp_path / "notes" / "my_node_modules_writeup.md"
        assert not indexer._should_exclude(p)

    def test_kb_rooted_under_git_mirror_not_excluded(
        self, tmp_path, monkeypatch, patched_indexer_runtime
    ):
        """A KB rooted under a path that contains .git in a parent segment is not excluded."""
        mirror = tmp_path / ".git-mirror" / "docs"
        mirror.mkdir(parents=True)
        indexer = self._make_indexer(mirror, patched_indexer_runtime, monkeypatch)
        p = mirror / "intro.md"
        assert not indexer._should_exclude(p)

    def test_hidden_dir_within_kb_excluded_by_leading_dot(
        self, tmp_path, monkeypatch, patched_indexer_runtime
    ):
        """A file inside a .hidden dir is excluded because the part starts with '.'."""
        indexer = self._make_indexer(tmp_path, patched_indexer_runtime, monkeypatch)
        p = tmp_path / ".venv" / "lib" / "site.py"
        assert indexer._should_exclude(p)

    def test_hidden_parent_outside_kb_is_not_excluded(
        self, tmp_path, monkeypatch, patched_indexer_runtime
    ):
        """Only KB-relative hidden parts should be excluded."""
        kb = tmp_path / ".mirror" / "docs"
        kb.mkdir(parents=True)
        indexer = self._make_indexer(kb, patched_indexer_runtime, monkeypatch)
        assert not indexer._should_exclude(kb / "intro.md")


class TestAtomicChromaReset:
    """Tests for _clear_chroma_collection atomicity."""

    def test_count_is_zero_after_reset(
        self, tmp_path, monkeypatch, patched_indexer_runtime
    ):
        """After _clear_chroma_collection, count() must be 0."""
        from trace_search.config import get_settings

        monkeypatch.setenv("KB_PATH", str(tmp_path))
        get_settings.cache_clear()
        try:
            indexer = patched_indexer_runtime.WikiIndexer()
            indexer.collection.add(
                ids=["doc::0"],
                documents=["content"],
                embeddings=[[0.1, 0.0, 0.0]],
                metadatas=[
                    {"path": "doc.md", "title": "Doc", "folder": "", "chunk_index": 0}
                ],
            )
            assert indexer.collection.count() == 1

            indexer._clear_chroma_collection()

            assert indexer.collection.count() == 0
        finally:
            get_settings.cache_clear()

    def test_new_handle_accepts_writes_after_reset(
        self, tmp_path, monkeypatch, patched_indexer_runtime
    ):
        """Writes after reset should land in the new collection handle."""
        from trace_search.config import get_settings

        monkeypatch.setenv("KB_PATH", str(tmp_path))
        get_settings.cache_clear()
        try:
            indexer = patched_indexer_runtime.WikiIndexer()
            indexer._clear_chroma_collection()

            indexer.collection.add(
                ids=["new::0"],
                documents=["new content"],
                embeddings=[[0.5, 0.0, 0.0]],
                metadatas=[
                    {"path": "new.md", "title": "New", "folder": "", "chunk_index": 0}
                ],
            )
            assert indexer.collection.count() == 1
        finally:
            get_settings.cache_clear()
