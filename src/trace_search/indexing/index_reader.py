"""Read immutable index generations and resolve chunk neighbors."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from trace_search.config import Settings
from trace_search.indexing.index_paths import chunk_id
from trace_search.indexing.index_store import IndexSnapshot, load_snapshot, read_current

logger = logging.getLogger(__name__)


class IndexReader:
    def __init__(self, kb_path: Path, index_root: Path, config: Settings):
        self.kb_path = kb_path
        self.index_root = index_root
        self.config = config
        self._snapshot: IndexSnapshot | None = None
        self._lock = threading.Lock()

    def has_index(self) -> bool:
        return read_current(self.index_root) is not None

    def install(self, snapshot: IndexSnapshot) -> None:
        with self._lock:
            self._snapshot = snapshot

    def snapshot(self) -> IndexSnapshot:
        """Return the current generation, reloading it when a new one was published.

        Costs one small file read per call. A reindex by any process, including
        a CLI run beside a long-lived server, is picked up on the next search.
        """
        current = read_current(self.index_root)
        loaded = self._snapshot
        if loaded is not None and loaded.generation == current:
            return loaded
        with self._lock:
            loaded = self._snapshot
            if loaded is None or loaded.generation != read_current(self.index_root):
                fresh = load_snapshot(self.index_root)
                if fresh is not None:
                    logger.info(
                        "Loaded index generation %s for %s (%d chunks)",
                        fresh.generation,
                        self.kb_path,
                        len(fresh),
                    )
                loaded = fresh if fresh is not None else IndexSnapshot.empty()
                self._snapshot = loaded
            return loaded

    def neighbor_contents_batch(
        self,
        requests: list[tuple[str, int | None, int | None]],
        snapshot: IndexSnapshot | None = None,
    ) -> list[str | None]:
        """Return the text of each hit's previous and next chunk, joined."""
        snapshot = snapshot if snapshot is not None else self.snapshot()
        output: list[str | None] = []
        for path, chunk_index, chunk_count in requests:
            if chunk_index is None or chunk_count is None or chunk_count <= 1:
                output.append(None)
                continue
            docs = [
                snapshot.texts[snapshot.row_by_id[cid]]
                for i in (chunk_index - 1, chunk_index + 1)
                if 0 <= i < chunk_count
                and (cid := chunk_id(path, i)) in snapshot.row_by_id
            ]
            output.append("\n\n".join(docs) if docs else None)
        return output

    def get_stats(self) -> dict[str, object]:
        """Get index statistics."""
        snapshot = self.snapshot()
        return {
            "total_chunks": len(snapshot),
            "documents": len({chunk["path"] for chunk in snapshot.chunks}),
            "generation": snapshot.generation or "none (run reindex)",
            "kb_path": str(self.kb_path),
            "index_root": str(self.index_root),
            "embedding_model": snapshot.metadata.embedding_model
            if snapshot.metadata
            else "none (run reindex)",
            "embedding_dims": snapshot.metadata.embedding_dims
            if snapshot.metadata
            else 0,
            "embedding_backend": snapshot.metadata.embedding_backend
            if snapshot.metadata
            else "none",
            "chunking": {
                "char_chunk_size": snapshot.metadata.char_chunk_size
                if snapshot.metadata
                else self.config.char_chunk_size,
                "char_overlap_size": snapshot.metadata.char_overlap_size
                if snapshot.metadata
                else self.config.char_overlap_size,
            },
        }
