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
import re
import shutil
import stat
import tempfile
import threading
import time
from collections.abc import Callable, Generator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, NotRequired, TypedDict, cast

import bm25s
import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

from trace_search.indexing.bm25_tokenize import english_stemmer
from trace_search.indexing.embeddings import EmbeddingArray
from trace_search.indexing.index_metadata import (
    IndexMetadata,
    index_metadata_from_dict,
)

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
_HELD_LOCKS = threading.local()
_GENERATION_NAME = re.compile(r"gen-[A-Za-z0-9_-]+\Z")


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


class _StoredChunk(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    path: str = Field(min_length=1)
    title: str
    folder: str
    chunk_index: int = Field(ge=0)
    chunk_count: int = Field(gt=0)
    breadcrumb: str
    extension: str
    source_mtime: FiniteFloat
    aliases: str | None = None
    status: str | None = None
    as_of: str | None = None


OPTIONAL_CHUNK_METADATA_FIELDS = tuple(
    name for name, definition in _StoredChunk.model_fields.items() if not definition.is_required()
)


class _StoredRows(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    ids: list[str]
    texts: list[str]
    chunks: list[_StoredChunk]

    @model_validator(mode="after")
    def aligned_rows(self) -> _StoredRows:
        if (
            len(self.ids) != len(self.texts)
            or len(self.ids) != len(self.chunks)
            or len(set(self.ids)) != len(self.ids)
        ):
            raise ValueError("Index chunk rows must align and have unique ids")
        positions: dict[str, list[int]] = {}
        counts: dict[str, int] = {}
        for cid, chunk in zip(self.ids, self.chunks, strict=True):
            path = Path(chunk.path)
            if (
                path.is_absolute()
                or ".." in path.parts
                or cid != f"{chunk.path}::{chunk.chunk_index}"
            ):
                raise ValueError("Invalid chunk path or identity")
            positions.setdefault(chunk.path, []).append(chunk.chunk_index)
            if chunk.path in counts and counts[chunk.path] != chunk.chunk_count:
                raise ValueError("Inconsistent document chunk count")
            counts[chunk.path] = chunk.chunk_count
        if any(sorted(indices) != list(range(counts[path])) for path, indices in positions.items()):
            raise ValueError("Document chunks must include each declared position once")
        return self


class IndexBusyError(RuntimeError):
    """Another process holds the index writer lock."""


class IndexCorruptError(RuntimeError):
    """The current generation's files cannot be read."""


@contextmanager
def writer_lock(index_root: Path) -> Generator[None]:
    """Hold the exclusive writer lock for an index root, or fail immediately.

    The lock is advisory ``flock`` on ``<index_root>/.write.lock``; the kernel
    releases it when the holder exits, even on a crash, so a dead writer never
    wedges the index.
    """
    index_root.mkdir(parents=True, exist_ok=True)
    lock_path = index_root / LOCK_FILENAME
    try:
        lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    except OSError as exc:
        raise IndexCorruptError(f"Cannot safely open index writer lock {lock_path}: {exc}") from exc
    with os.fdopen(lock_fd, "r+", encoding="utf-8") as handle:
        lock_stat = os.fstat(handle.fileno())
        if not stat.S_ISREG(lock_stat.st_mode) or lock_stat.st_nlink != 1:
            raise IndexCorruptError(
                f"Index writer lock must be a regular file with one link: {lock_path}"
            )
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
        owner_pid = os.getpid()
        held: dict[Path, int] = getattr(_HELD_LOCKS, "roots", {})
        _HELD_LOCKS.roots = {**held, index_root.resolve(): owner_pid}
        try:
            yield
        finally:
            _HELD_LOCKS.roots = held
            if os.getpid() == owner_pid:
                handle.seek(0)
                handle.truncate()
                fcntl.flock(handle, fcntl.LOCK_UN)


def read_current(index_root: Path) -> str | None:
    """Return the generation name ``CURRENT`` points at, or None when unbuilt."""
    try:
        name = (index_root / CURRENT_FILENAME).read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    if name and not _GENERATION_NAME.fullmatch(name):
        raise IndexCorruptError(
            f"Invalid CURRENT pointer in {index_root}. Run `reindex` to rebuild it."
        )
    if name and not (index_root / name).resolve().is_relative_to(index_root.resolve()):
        raise IndexCorruptError(
            f"CURRENT points outside {index_root}. Run `reindex` to rebuild it."
        )
    return name or None


def _tokenize(texts: list[str]) -> Any:
    return bm25s.tokenize(texts, stopwords="en", stemmer=english_stemmer(), show_progress=False)


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
    chunk_ids: Sequence[str]
    texts: Sequence[str]
    chunks: Sequence[ChunkMetadata]
    embeddings: EmbeddingArray
    bm25: bm25s.BM25 | None
    row_by_id: Mapping[str, int] = field(default_factory=dict, compare=False)
    _row_terms: dict[int, frozenset[str]] = field(default_factory=dict, compare=False, repr=False)

    def __post_init__(self) -> None:
        if self.embeddings.ndim != 2 or not np.isfinite(self.embeddings).all():
            raise ValueError("Index embeddings must be a finite two-dimensional matrix")
        rows = len(self.chunk_ids)
        if len(set(self.chunk_ids)) != rows:
            raise ValueError("Index chunk ids must be unique")
        if self.metadata is not None and (
            self.metadata.chunk_count != rows
            or (self.metadata.embedding_dims != self.embeddings.shape[1])
        ):
            raise ValueError("Index metadata dimensions or chunk count do not match payload")
        if self.metadata is not None and self.metadata.version >= 7:
            documents = {chunk["path"] for chunk in self.chunks}
            source_paths = {record.path for record in self.metadata.source_files}
            if self.metadata.document_count != len(documents):
                raise ValueError("Index metadata document count does not match chunk payload")
            if not documents <= source_paths:
                raise ValueError("Index chunks refer to documents absent from the source inventory")
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
        if self.metadata is not None and self.bm25 is not None:
            if (
                self.bm25.scores["num_docs"] != rows
                or not np.isfinite(self.bm25.scores["data"]).all()
            ):
                raise ValueError("BM25 rows or scores do not match the index payload")
            if self.metadata.version >= 7 and (
                self.bm25.k1 != self.metadata.bm25_k1 or self.bm25.b != self.metadata.bm25_b
            ):
                raise ValueError("BM25 parameters do not match the persisted build recipe")
        object.__setattr__(self, "chunk_ids", tuple(self.chunk_ids))
        object.__setattr__(self, "texts", tuple(self.texts))
        object.__setattr__(
            self,
            "chunks",
            tuple(cast(ChunkMetadata, MappingProxyType(dict(chunk))) for chunk in self.chunks),
        )
        object.__setattr__(
            self,
            "row_by_id",
            MappingProxyType({cid: i for i, cid in enumerate(self.chunk_ids)}),
        )
        vectors = np.frombuffer(
            self.embeddings.astype(np.float32).tobytes(), dtype=np.float32
        ).reshape(self.embeddings.shape)
        vectors.setflags(write=False)
        object.__setattr__(self, "embeddings", vectors)

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

    def row_terms(self, row: int, extract: Callable[[str], frozenset[str]]) -> frozenset[str]:
        """Terms of one chunk's text, computed once per snapshot.

        Cached here rather than globally so the cache is bounded by the corpus
        and released with the generation it belongs to.
        """
        terms = self._row_terms.get(row)
        if terms is None:
            terms = extract(self.texts[row])
            self._row_terms[row] = terms
        return terms

    def row_mask(self, key: object, keep: Callable[[ChunkMetadata], bool]) -> NDArray[np.bool_]:
        """Evaluate a request mask without retaining arbitrary request filters."""
        return np.fromiter((keep(chunk) for chunk in self.chunks), dtype=np.bool_, count=len(self))


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
    """Publish under the physical writer lock, including direct library calls."""
    if getattr(_HELD_LOCKS, "roots", {}).get(index_root.resolve()) == os.getpid():
        return _write_snapshot_locked(index_root, snapshot)
    with writer_lock(index_root):
        return _write_snapshot_locked(index_root, snapshot)


def _write_snapshot_locked(index_root: Path, snapshot: IndexSnapshot) -> IndexSnapshot:
    """Persist a snapshot as a new generation and point ``CURRENT`` at it.

    Callers must hold `writer_lock`. Returns the snapshot stamped with its
    generation name.
    """
    if snapshot.metadata is None:
        raise ValueError("Cannot persist an index generation without metadata")
    _StoredRows.model_validate(
        {
            "ids": list(snapshot.chunk_ids),
            "texts": list(snapshot.texts),
            "chunks": [dict(chunk) for chunk in snapshot.chunks],
        }
    )
    if index_metadata_from_dict(snapshot.metadata.to_dict()) is None:
        raise ValueError(
            f"Cannot publish unsupported index metadata schema v{snapshot.metadata.version}"
        )
    # One clock read, so names sort in build order even across a second boundary.
    now_ns = time.time_ns()
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime(now_ns // 10**9))
    name = f"{_GENERATION_PREFIX}{stamp}-{now_ns % 10**9:09d}"
    tmp_dir = _generation_dir(index_root, name + _TMP_SUFFIX)
    tmp_dir.mkdir(parents=True)

    pointer_tmp: Path | None = None
    generation_dir = _generation_dir(index_root, name)
    renamed = False
    published = False
    try:
        (tmp_dir / _CHUNKS_FILENAME).write_text(
            json.dumps(
                {
                    "ids": list(snapshot.chunk_ids),
                    "texts": list(snapshot.texts),
                    "chunks": [dict(chunk) for chunk in snapshot.chunks],
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
        tmp_dir.rename(generation_dir)
        renamed = True
        _fsync(index_root)

        pointer_fd, pointer_name = tempfile.mkstemp(
            prefix=".CURRENT-", suffix=".tmp", dir=index_root
        )
        pointer_tmp = Path(pointer_name)
        with os.fdopen(pointer_fd, "w", encoding="utf-8") as pointer:
            pointer.write(name)
            pointer.flush()
            os.fsync(pointer.fileno())
        Path(pointer_tmp).replace(index_root / CURRENT_FILENAME)
        published = True
        _fsync(index_root)
    except BaseException:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        if renamed and not published:
            shutil.rmtree(generation_dir, ignore_errors=True)
        if pointer_tmp is not None:
            pointer_tmp.unlink(missing_ok=True)
        raise
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
    raw_chunks = _StoredRows.model_validate_json(
        (gen_dir / _CHUNKS_FILENAME).read_text(encoding="utf-8")
    )
    embeddings = np.load(gen_dir / _EMBEDDINGS_FILENAME, allow_pickle=False)
    metadata = index_metadata_from_dict(
        json.loads((gen_dir / _METADATA_FILENAME).read_text(encoding="utf-8"))
    )
    chunks = [
        cast(ChunkMetadata, chunk.model_dump(exclude_none=True)) for chunk in raw_chunks.chunks
    ]
    if metadata is None:
        raise ValueError("Unknown index metadata schema. Run `reindex` to rebuild it.")
    bm25_dir = gen_dir / _BM25_DIRNAME
    if raw_chunks.texts and not bm25_dir.is_dir():
        # A writer pruned this generation mid-load; let the caller retry.
        raise FileNotFoundError(bm25_dir)
    bm25 = bm25s.BM25.load(str(bm25_dir)) if bm25_dir.is_dir() else None
    return IndexSnapshot(
        generation=name,
        metadata=metadata,
        chunk_ids=raw_chunks.ids,
        texts=raw_chunks.texts,
        chunks=chunks,
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
        except FileNotFoundError as exc:
            if attempt == _LOAD_ATTEMPTS - 1:
                raise IndexCorruptError(
                    f"Index generation {name} is missing files. Run `reindex` to rebuild it."
                ) from exc
            logger.info("Index generation %s vanished mid-load; retrying", name)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
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
            (_generation_dir(index_root, name) / _METADATA_FILENAME).read_text(encoding="utf-8")
        )
    except OSError, ValueError:
        return None
    return index_metadata_from_dict(raw) if isinstance(raw, dict) else None
