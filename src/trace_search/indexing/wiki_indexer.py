"""Public handle for reading and building one index."""

from __future__ import annotations

import threading
from pathlib import Path

from trace_search.config import Settings, get_settings
from trace_search.indexing.embeddings import EmbeddingBackend, build_embedding_backend
from trace_search.indexing.index_builder import BackendProvider, IndexBuilder
from trace_search.indexing.index_reader import IndexReader
from trace_search.indexing.index_store import IndexSnapshot
from trace_search.indexing.kb_paths import get_default_index_root

__all__ = ["BackendProvider", "WikiIndexer"]


class WikiIndexer:
    """Compose the index reader and builder behind one public constructor."""

    def __init__(
        self,
        kb_path: str | Path | None = None,
        index_root: str | Path | None = None,
        backend: EmbeddingBackend | BackendProvider | None = None,
        *,
        config: Settings | None = None,
    ):
        self.config = (config or get_settings()).model_copy(deep=True)
        self.kb_path = (
            Path(kb_path) if kb_path is not None else self.config.resolved_kb_path
        ).resolve()
        if not self.kb_path.is_dir():
            raise ValueError(f"Knowledge base path is not a directory: {self.kb_path}")
        self.index_root = (
            Path(index_root)
            if index_root is not None
            else get_default_index_root(self.kb_path, self.config.index_path)
        )
        if backend is None:
            self._backend_provider: BackendProvider = lambda: build_embedding_backend(self.config)
        elif isinstance(backend, EmbeddingBackend):
            self._backend_provider = lambda: backend
        else:
            self._backend_provider = backend
        self._backend: EmbeddingBackend | None = None
        self._backend_lock = threading.Lock()
        self.reader = IndexReader(self.kb_path, self.index_root, self.config)
        self.builder = IndexBuilder(self.reader, lambda: self.backend, self.config)

    @property
    def backend(self) -> EmbeddingBackend:
        with self._backend_lock:
            if self._backend is None:
                self._backend = self._backend_provider()
            return self._backend

    def has_index(self) -> bool:
        return self.reader.has_index()

    def snapshot(self) -> IndexSnapshot:
        return self.reader.snapshot()

    def build_index(self, force: bool = False) -> int:
        return self.builder.build_index(force)

    def neighbor_contents_batch(
        self,
        requests: list[tuple[str, int | None, int | None]],
        snapshot: IndexSnapshot | None = None,
    ) -> list[str | None]:
        return self.reader.neighbor_contents_batch(requests, snapshot)

    def get_stats(self) -> dict[str, object]:
        return self.reader.get_stats()
