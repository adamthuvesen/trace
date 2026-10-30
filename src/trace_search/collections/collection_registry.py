"""Multi-collection orchestration for Trace."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

from trace_search.config import Settings, get_settings
from trace_search.filesystem_paths import validate_distinct_targets
from trace_search.indexing.embeddings import EmbeddingBackend, build_embedding_backend
from trace_search.indexing.kb_paths import get_default_index_root
from trace_search.indexing.embedding_warmup import warm_embedding_model
from trace_search.indexing.wiki_indexer import BackendProvider, WikiIndexer


@dataclass
class Collection:
    """A knowledge base collection with its own lazily opened index."""

    name: str
    kb_path: Path
    index_path: Path
    config: Settings = field(default_factory=get_settings, repr=False)
    _indexer: WikiIndexer | None = field(default=None, repr=False)
    # Keeps two first queries from both opening the indexer or both building a
    # missing index. Searches themselves need no lock: each one reads one
    # immutable snapshot, and a reindex publishes a new snapshot atomically.
    _lock: threading.Lock = field(
        default_factory=threading.Lock, repr=False, compare=False
    )

    def indexer(
        self, backend: BackendProvider, *, build_if_missing: bool = True
    ) -> WikiIndexer:
        """Open the indexer; build the index first when none exists yet."""
        with self._lock:
            if self._indexer is None:
                self._indexer = WikiIndexer(
                    kb_path=self.kb_path,
                    index_root=self.index_path,
                    backend=backend,
                    config=self.config,
                )
            if build_if_missing and not self._indexer.has_index():
                self._indexer.build_index()
            return self._indexer

    def rebuild(self, backend: BackendProvider, *, force: bool = False) -> int:
        """Reindex this collection and return the resulting chunk count.

        Incremental by default; ``force=True`` rebuilds every file. Raises
        `IndexBusyError` when another process is already reindexing it.
        """
        return self.indexer(backend, build_if_missing=False).build_index(force=force)


class CollectionRegistry:
    """Manages multiple knowledge base collections with a shared embedding model."""

    def __init__(
        self,
        collections: dict[str, Path],
        index_root: Path | None = None,
        *,
        config: Settings | None = None,
    ):
        self.config = (config or get_settings()).model_copy(deep=True)
        self._backend: EmbeddingBackend | None = None
        self._warmed: bool = False
        self._backend_lock = threading.Lock()
        idx_root = index_root if index_root is not None else self.config.index_path
        self._index_root = idx_root

        self.collections: dict[str, Collection] = {}
        if not collections:
            raise ValueError("At least one collection is required")
        for name, kb_path in collections.items():
            if (
                not name
                or name.lower() == "all"
                or name in {".", ".."}
                or any(part in name for part in ("/", "\\", "\0"))
            ):
                raise ValueError(f"Invalid collection name: {name!r}")
            kb_path = Path(kb_path).expanduser().resolve()
            if not kb_path.is_dir():
                raise ValueError(
                    f"Collection '{name}' path is not a directory: {kb_path}"
                )
            col_index = get_default_index_root(
                kb_path, idx_root, name if idx_root else None
            )
            self.collections[name] = Collection(
                name=name,
                kb_path=kb_path,
                index_path=col_index,
                config=self.config,
            )

        validate_distinct_targets(
            [
                (f"collection '{col.name}' index", col.index_path / "CURRENT")
                for col in self.collections.values()
            ]
        )

    @property
    def collection_names(self) -> list[str]:
        return sorted(self.collections.keys())

    def shared_backend(self) -> EmbeddingBackend:
        """The one embedding model all collections share, loaded on first use."""
        # Concurrent first queries would otherwise each load the model.
        with self._backend_lock:
            if self._backend is None:
                self._backend = build_embedding_backend(self.config)
                self._warm_backend()
            return self._backend

    def _warm_backend(self) -> None:
        """Warm the shared embedding backend exactly once per registry lifecycle."""
        if self._warmed:
            return
        assert self._backend is not None
        warm_embedding_model(self._backend)
        self._warmed = True

    def _resolve(self, collection: str | None) -> list[Collection]:
        """Resolve collection name to list of Collection objects."""
        if collection and collection.lower() != "all":
            col = self.collections.get(collection)
            if col is None:
                raise ValueError(
                    f"Unknown collection '{collection}'. "
                    f"Available: {', '.join(self.collection_names)}"
                )
            return [col]
        return list(self.collections.values())
