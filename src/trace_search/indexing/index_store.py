"""On-disk index generations: one immutable directory per build, swapped atomically.

Each successful build writes a complete generation directory (chunk texts and
metadata, a normalized embedding matrix, the BM25 index, and the source
inventory), then points ``CURRENT`` at it with an atomic rename. Readers load a
whole generation into memory as one immutable `IndexSnapshot` and reload when
``CURRENT`` changes, so a long-running server picks up another process's reindex
without a restart and never sees a half-written index. Writers hold an exclusive
``flock`` on the index root for the whole build: there is only ever one writer.
"""

from __future__ import annotations

import errno
import fcntl
import json
import logging
import os
import shutil
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NotRequired, TypedDict

import bm25s
import numpy as np
from numpy.typing import NDArray

from trace_search.indexing.embeddings import EmbeddingArray
from trace_search.indexing.index_metadata import (
    IndexMetadata,
    index_metadata_from_dict,
)
from trace_search.retrieval.bm25_tokenize import english_stemmer

logger = logging.getLogger(__name__)

CURRENT_FILENAME = "CURRENT"
LOCK_FILENAME = ".write.lock"
_GENERATION_PREFIX = "gen-"
_TMP_SUFFIX = ".tmp"
_CHUNKS_FILENAME = "chunks.json"
_EMBEDDINGS_FILENAME = "embeddings.npy"
_METADATA_FILENAME = "index_metadata.json"
_BM25_DIRNAME = "bm25"
# A reader can race a writer that prunes the generation it is loading; retry
# against the new CURRENT instead of failing the search.
_LOAD_ATTEMPTS = 3


class ChunkMetadata(TypedDict):
    """Per-chunk metadata stored with every indexed chunk."""

    path: str
    title: str
    folder: str
    chunk_index: int
    chunk_count: int
    breadcrumb: str
    extension: str
    source_mtime: float
    aliases: NotRequired[str]
    status: NotRequired[str]
    as_of: NotRequired[str]


class IndexBusyError(RuntimeError):
    """Another process holds the index writer lock."""


class IndexCorruptError(RuntimeError):
    """The current generation's files cannot be read."""


@contextmanager
def writer_lock(index_root: Path) -> Iterator[None]:
    """Hold the exclusive writer lock for an index root, or fail immediately.

    The lock is advisory ``flock`` on ``<index_root>/.write.lock``; the kernel
    releases it when the holder exits, even on a crash, so a dead writer never
    wedges the index.
    """
    index_root.mkdir(parents=True, exist_ok=True)
    lock_path = index_root / LOCK_FILENAME
    with open(lock_path, "a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                raise
            handle.seek(0)
            holder = handle.read().strip() or "unknown"
            raise IndexBusyError(
                f"Another Trace process (pid {holder}) is reindexing {index_root}. "
                "Retry when it finishes."
            ) from exc
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        try:
            yield
        finally:
            handle.seek(0)
            handle.truncate()
            fcntl.flock(handle, fcntl.LOCK_UN)


def read_current(index_root: Path) -> str | None:
    """Return the generation name ``CURRENT`` points at, or None when unbuilt."""
    try:
        name = (index_root / CURRENT_FILENAME).read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    return name or None


def _tokenize(texts: list[str]) -> Any:
    return bm25s.tokenize(
        texts, stopwords="en", stemmer=english_stemmer(), show_progress=False
    )


def build_bm25(texts: list[str], *, k1: float, b: float) -> bm25s.BM25:
    """Build an in-memory BM25 index over chunk texts."""
    bm25 = bm25s.BM25(k1=k1, b=b)
    bm25.index(_tokenize(texts), show_progress=False)
    return bm25


def normalize_rows(matrix: EmbeddingArray) -> EmbeddingArray:
    """L2-normalize rows so a dot product is cosine similarity."""
    if matrix.size == 0:
        return matrix.astype(np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return np.asarray(matrix / norms, dtype=np.float32)


@dataclass(frozen=True)
class IndexSnapshot:
    """One loaded index generation. Row ``i`` is the same chunk everywhere."""

    generation: str | None
    metadata: IndexMetadata | None
    chunk_ids: list[str]
    texts: list[str]
    chunks: list[ChunkMetadata]
    embeddings: EmbeddingArray
    bm25: bm25s.BM25 | None
    row_by_id: dict[str, int] = field(default_factory=dict, compare=False)
    _masks: dict[object, NDArray[np.bool_]] = field(
        default_factory=dict, compare=False, repr=False
    )
    _row_terms: dict[int, frozenset[str]] = field(
        default_factory=dict, compare=False, repr=False
    )

    def __post_init__(self) -> None:
        rows = len(self.chunk_ids)
        if not (
            len(self.texts) == rows
            and len(self.chunks) == rows
            and self.embeddings.shape[0] == rows
        ):
            raise ValueError(
                f"Index generation {self.generation} is inconsistent: "
                f"{rows} ids, {len(self.texts)} texts, {len(self.chunks)} chunk "
                f"records, {self.embeddings.shape[0]} embedding rows. Reindex with "
                "force=true."
            )
        if not self.row_by_id:
            self.row_by_id.update({cid: i for i, cid in enumerate(self.chunk_ids)})

    @classmethod
    def build(
        cls,
        *,
        chunk_ids: list[str],
        texts: list[str],
        chunks: list[ChunkMetadata],
        embeddings: EmbeddingArray,
        k1: float,
        b: float,
        metadata: IndexMetadata | None = None,
        generation: str | None = None,
    ) -> IndexSnapshot:
        """Assemble a snapshot in memory, building BM25 over ``texts``."""
        return cls(
            generation=generation,
            metadata=metadata,
            chunk_ids=chunk_ids,
            texts=texts,
            chunks=chunks,
            embeddings=normalize_rows(embeddings),
            bm25=build_bm25(texts, k1=k1, b=b) if texts else None,
        )

    @classmethod
    def empty(cls, dim: int = 0) -> IndexSnapshot:
        return cls(
            generation=None,
            metadata=None,
            chunk_ids=[],
            texts=[],
            chunks=[],
            embeddings=np.empty((0, dim), dtype=np.float32),
            bm25=None,
        )

    def __len__(self) -> int:
        return len(self.chunk_ids)

    def row_terms(
        self, row: int, extract: Callable[[str], frozenset[str]]
    ) -> frozenset[str]:
        """Terms of one chunk's text, computed once per snapshot.

        Cached here rather than globally so the cache is bounded by the corpus
        and released with the generation it belongs to.
        """
        terms = self._row_terms.get(row)
        if terms is None:
            terms = extract(self.texts[row])
            self._row_terms[row] = terms
        return terms

    def row_mask(self, key: object, keep: Any) -> NDArray[np.bool_]:
        """Boolean row mask for a filter, cached per snapshot by ``key``."""
        mask = self._masks.get(key)
        if mask is None:
            mask = np.fromiter(
                (keep(chunk) for chunk in self.chunks), dtype=np.bool_, count=len(self)
            )
            self._masks[key] = mask
        return mask


def _generation_dir(index_root: Path, name: str) -> Path:
    return index_root / name


def _fsync(path: Path) -> None:
    """Flush a file or directory entry to disk before it is published."""
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_snapshot(index_root: Path, snapshot: IndexSnapshot) -> IndexSnapshot:
    """Persist a snapshot as a new generation and point ``CURRENT`` at it.

    Callers must hold `writer_lock`. Returns the snapshot stamped with its
    generation name.
    """
    if snapshot.metadata is None:
        raise ValueError("Cannot persist an index generation without metadata")
    # One clock read, so names sort in build order even across a second boundary.
    now_ns = time.time_ns()
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime(now_ns // 10**9))
    name = f"{_GENERATION_PREFIX}{stamp}-{now_ns % 10**9:09d}"
    tmp_dir = _generation_dir(index_root, name + _TMP_SUFFIX)
    tmp_dir.mkdir(parents=True)

    (tmp_dir / _CHUNKS_FILENAME).write_text(
        json.dumps(
            {
                "ids": snapshot.chunk_ids,
                "texts": snapshot.texts,
                "chunks": snapshot.chunks,
            }
        ),
        encoding="utf-8",
    )
    np.save(tmp_dir / _EMBEDDINGS_FILENAME, snapshot.embeddings)
    if snapshot.bm25 is not None:
        snapshot.bm25.save(str(tmp_dir / _BM25_DIRNAME))
    (tmp_dir / _METADATA_FILENAME).write_text(
        json.dumps(snapshot.metadata.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    # A power loss must not leave CURRENT naming a generation whose files never
    # reached the disk. Directories are synced bottom-up so every entry
    # (including bm25/ and its files) is durable before the rename.
    for folder, _, files in os.walk(tmp_dir, topdown=False):
        for filename in files:
            _fsync(Path(folder) / filename)
        _fsync(Path(folder))
    tmp_dir.rename(_generation_dir(index_root, name))
    _fsync(index_root)

    pointer_tmp = index_root / (CURRENT_FILENAME + _TMP_SUFFIX)
    pointer_tmp.write_text(name, encoding="utf-8")
    _fsync(pointer_tmp)
    os.replace(pointer_tmp, index_root / CURRENT_FILENAME)
    _fsync(index_root)
    _prune_generations(index_root, keep=name)
    logger.info("Published index generation %s (%d chunks)", name, len(snapshot))

    return IndexSnapshot(
        generation=name,
        metadata=snapshot.metadata,
        chunk_ids=snapshot.chunk_ids,
        texts=snapshot.texts,
        chunks=snapshot.chunks,
        embeddings=snapshot.embeddings,
        bm25=snapshot.bm25,
        row_by_id=snapshot.row_by_id,
    )


def _prune_generations(index_root: Path, *, keep: str) -> None:
    """Delete old generations, keeping ``keep`` and its predecessor.

    The predecessor survives one more build so a reader that read ``CURRENT``
    just before the swap can still finish loading it.
    """
    generations = sorted(
        path
        for path in index_root.iterdir()
        if path.is_dir() and path.name.startswith(_GENERATION_PREFIX)
    )
    finished = [p for p in generations if not p.name.endswith(_TMP_SUFFIX)]
    # Leftover .tmp directories come from a writer that died mid-build; the
    # writer lock guarantees none is in progress now.
    doomed = [p for p in generations if p.name.endswith(_TMP_SUFFIX)]
    older = [p for p in finished if p.name < keep]
    doomed.extend(older[:-1])
    for path in doomed:
        shutil.rmtree(path, ignore_errors=True)


def _load_generation(index_root: Path, name: str) -> IndexSnapshot:
    gen_dir = _generation_dir(index_root, name)
    raw_chunks = json.loads((gen_dir / _CHUNKS_FILENAME).read_text(encoding="utf-8"))
    embeddings = np.load(gen_dir / _EMBEDDINGS_FILENAME, allow_pickle=False)
    metadata = index_metadata_from_dict(
        json.loads((gen_dir / _METADATA_FILENAME).read_text(encoding="utf-8"))
    )
    bm25_dir = gen_dir / _BM25_DIRNAME
    if raw_chunks["texts"] and not bm25_dir.is_dir():
        # A writer pruned this generation mid-load; let the caller retry.
        raise FileNotFoundError(bm25_dir)
    bm25 = bm25s.BM25.load(str(bm25_dir)) if bm25_dir.is_dir() else None
    return IndexSnapshot(
        generation=name,
        metadata=metadata,
        chunk_ids=list(raw_chunks["ids"]),
        texts=list(raw_chunks["texts"]),
        chunks=list(raw_chunks["chunks"]),
        embeddings=np.asarray(embeddings, dtype=np.float32),
        bm25=bm25,
    )


def load_snapshot(index_root: Path) -> IndexSnapshot | None:
    """Load the generation ``CURRENT`` names, or None when the index is unbuilt."""
    for attempt in range(_LOAD_ATTEMPTS):
        name = read_current(index_root)
        if name is None:
            return None
        try:
            return _load_generation(index_root, name)
        except FileNotFoundError:
            if attempt == _LOAD_ATTEMPTS - 1:
                raise
            logger.info("Index generation %s vanished mid-load; retrying", name)
        except (OSError, ValueError, KeyError) as exc:
            raise IndexCorruptError(
                f"Index generation {name} in {index_root} is unreadable ({exc}). "
                "Run `reindex` to rebuild it."
            ) from exc
    return None


def read_current_metadata(index_root: Path) -> IndexMetadata | None:
    """Read only the source inventory of the current generation (cheap)."""
    name = read_current(index_root)
    if name is None:
        return None
    try:
        raw = json.loads(
            (_generation_dir(index_root, name) / _METADATA_FILENAME).read_text(
                encoding="utf-8"
            )
        )
    except (OSError, ValueError):
        return None
    return index_metadata_from_dict(raw) if isinstance(raw, dict) else None
