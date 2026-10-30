"""Versioned metadata for Trace search indexes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator

from trace_search.config import Settings, get_settings
from trace_search.indexing.embeddings import EmbeddingBackend
from trace_search.extraction.corpus import iter_kb_files

# v4: generation store (no Chroma). v5: frontmatter-aware chunks. v6: records
# chunk settings.
INDEX_METADATA_VERSION = 7
TOKENIZER_VERSION = "english-snowball-v1"
TRANSFORMATION_VERSION = "frontmatter-context-heading-v1"

_HASH_CHUNK_SIZE = 64 * 1024


@dataclass(frozen=True)
class SourceFileRecord:
    """A source file captured at index-build time."""

    path: str
    extension: str
    mtime: float
    size: int
    content_sha: str = ""


@dataclass(frozen=True)
class SourceChangeSet:
    """Categorized file changes since the last successful build."""

    unchanged: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    inventory: list[SourceFileRecord] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.changed or self.removed)


@dataclass(frozen=True)
class IndexMetadata:
    """Versioned metadata describing one built Trace index."""

    version: int
    build_started_at: str
    build_completed_at: str
    embedding_model: str
    model_slug: str
    embedding_dims: int
    char_chunk_size: int
    char_overlap_size: int
    document_count: int
    chunk_count: int
    source_files: Sequence[SourceFileRecord]
    warnings: Sequence[str]

    embedding_backend: str = "onnx"
    bm25_k1: float = 1.2
    bm25_b: float = 0.5
    tokenizer_version: str = TOKENIZER_VERSION
    transformation_version: str = TRANSFORMATION_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_files", tuple(self.source_files))
        object.__setattr__(self, "warnings", tuple(self.warnings))

    @property
    def build_recipe(self) -> dict[str, str | int | float]:
        return {
            "embedding_model": self.embedding_model,
            "embedding_backend": self.embedding_backend,
            "embedding_dims": self.embedding_dims,
            "char_chunk_size": self.char_chunk_size,
            "char_overlap_size": self.char_overlap_size,
            "bm25_k1": self.bm25_k1,
            "bm25_b": self.bm25_b,
            "tokenizer_version": self.tokenizer_version,
            "transformation_version": self.transformation_version,
        }

    @property
    def recipe_fingerprint(self) -> str:
        encoded = json.dumps(self.build_recipe, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable metadata dictionary."""
        data = asdict(self)
        data["source_files"] = list(data["source_files"])
        data["warnings"] = list(data["warnings"])
        return data


def utc_now_iso() -> str:
    """Return a stable UTC timestamp string."""
    return datetime.now(UTC).isoformat()


def hash_file(path: Path) -> str:
    """Return the SHA-256 hex digest of a file, read in fixed-size chunks."""
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(_HASH_CHUNK_SIZE), b""):
            hasher.update(block)
    return hasher.hexdigest()


def collect_source_files(
    kb_path: Path,
    prior: list[SourceFileRecord] | None = None,
    *,
    config: Settings | None = None,
) -> list[SourceFileRecord]:
    """Collect visible supported source files with fingerprints.

    When `prior` is supplied, files whose `(mtime, size)` match the prior record
    reuse the recorded `content_sha` so a hash is computed only for new or
    modified files. Without `prior`, every file is hashed from scratch.
    """
    prior_by_path: dict[str, SourceFileRecord] = {}
    if prior is not None:
        for record in prior:
            prior_by_path[record.path] = record

    records: list[SourceFileRecord] = []
    for file_path in iter_kb_files(
        kb_path, exclude_patterns=(config or get_settings()).exclude_patterns_list
    ):
        stat = file_path.stat()
        rel = str(file_path.relative_to(kb_path))
        previous = prior_by_path.get(rel)
        if (
            previous is not None
            and previous.content_sha
            and previous.mtime == stat.st_mtime
            and previous.size == stat.st_size
        ):
            content_sha = previous.content_sha
        else:
            content_sha = hash_file(file_path)
        after = file_path.stat()
        if (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino) != (
            after.st_mtime_ns,
            after.st_ctime_ns,
            after.st_size,
            after.st_ino,
        ):
            raise RuntimeError(f"Source changed during capture: {rel}. Retry reindex.")
        records.append(
            SourceFileRecord(
                path=rel,
                extension=file_path.suffix.lower(),
                mtime=stat.st_mtime,
                size=stat.st_size,
                content_sha=content_sha,
            )
        )
    return sorted(records, key=lambda record: record.path)


def build_index_metadata(
    *,
    kb_path: Path,
    build_started_at: str,
    build_completed_at: str,
    document_count: int,
    chunk_count: int,
    warnings: list[str] | None = None,
    source_files: list[SourceFileRecord] | None = None,
    config: Settings | None = None,
    backend: EmbeddingBackend | None = None,
) -> IndexMetadata:
    """Create metadata for the active settings and source tree.

    If `source_files` is supplied (e.g. computed earlier during an incremental
    rebuild) it is used verbatim; otherwise files are rescanned and hashed.
    """
    config = config or get_settings()
    if source_files is None:
        source_files = collect_source_files(kb_path, config=config)
    return IndexMetadata(
        version=INDEX_METADATA_VERSION,
        build_started_at=build_started_at,
        build_completed_at=build_completed_at,
        embedding_model=backend.model_name
        if backend is not None
        else config.embedding_model,
        model_slug=(
            backend.model_name.replace("/", "_").replace("-", "_").lower()
            if backend is not None
            else config.model_slug
        ),
        embedding_dims=backend.dim if backend is not None else config.embedding_dims,
        char_chunk_size=config.char_chunk_size,
        char_overlap_size=config.char_overlap_size,
        document_count=document_count,
        chunk_count=chunk_count,
        source_files=source_files,
        warnings=warnings or [],
        embedding_backend=backend_identity(backend) if backend is not None else "onnx",
        bm25_k1=config.bm25_k1,
        bm25_b=config.bm25_b,
    )


class _StoredSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    path: str = Field(min_length=1)
    extension: str
    mtime: FiniteFloat
    size: int = Field(ge=0)
    content_sha: str

    @field_validator("path")
    @classmethod
    def bounded_path(cls, value: str) -> str:
        if Path(value).is_absolute() or ".." in Path(value).parts:
            raise ValueError("Source path must stay inside the collection")
        return value


class _StoredMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: int
    build_started_at: str
    build_completed_at: str
    embedding_model: str = Field(min_length=1)
    model_slug: str = Field(min_length=1)
    embedding_dims: int = Field(ge=0)
    char_chunk_size: int = Field(gt=0)
    char_overlap_size: int = Field(ge=0)
    document_count: int = Field(ge=0)
    chunk_count: int = Field(ge=0)
    source_files: list[_StoredSource]
    warnings: list[str]
    embedding_backend: str = Field(min_length=1)
    bm25_k1: FiniteFloat = Field(gt=0)
    bm25_b: FiniteFloat = Field(ge=0, le=1)
    tokenizer_version: str = Field(min_length=1)
    transformation_version: str = Field(min_length=1)


def index_metadata_from_dict(raw: dict[str, Any]) -> IndexMetadata | None:
    """Decode v6 explicitly and reject malformed persisted v7 data."""
    version = raw.get("version")
    if version not in (6, INDEX_METADATA_VERSION):
        return None
    if version == 6:
        raw = {
            **raw,
            "embedding_backend": "onnx",
            "bm25_k1": 1.2,
            "bm25_b": 0.5,
            "tokenizer_version": "legacy-v6",
            "transformation_version": "legacy-v6",
        }
    decoded = _StoredMetadata.model_validate(raw)
    if len({record.path for record in decoded.source_files}) != len(
        decoded.source_files
    ):
        raise ValueError("Index source paths must be unique")
    fields = decoded.model_dump(exclude={"source_files"})
    return IndexMetadata(
        **fields,
        source_files=[
            SourceFileRecord(**record.model_dump()) for record in decoded.source_files
        ],
    )


def backend_identity(backend: EmbeddingBackend) -> str:
    """Identify the runtime that produced the vectors, including injected backends."""
    cls = type(backend)
    return (
        "onnx"
        if cls.__name__ == "OnnxBackend"
        else f"{cls.__module__}.{cls.__qualname__}"
    )


def metadata_query_compatible(
    metadata: IndexMetadata, config: Settings, backend: EmbeddingBackend | None = None
) -> bool:
    model = backend.model_name if backend is not None else config.embedding_model
    dims = backend.dim if backend is not None else config.embedding_dims
    runtime = backend_identity(backend) if backend is not None else "onnx"
    return (
        metadata.embedding_model == model
        and metadata.embedding_dims == dims
        and metadata.embedding_backend == runtime
    )


def metadata_matches_settings(
    metadata: IndexMetadata,
    config: Settings | None = None,
    backend: EmbeddingBackend | None = None,
) -> bool:
    """Whether all persisted build inputs permit incremental reuse."""
    config = config or get_settings()
    return bool(
        metadata.version == INDEX_METADATA_VERSION
        and metadata_query_compatible(metadata, config, backend)
        and metadata.char_chunk_size == config.char_chunk_size
        and metadata.char_overlap_size == config.char_overlap_size
        and metadata.bm25_k1 == config.bm25_k1
        and metadata.bm25_b == config.bm25_b
        and metadata.tokenizer_version == TOKENIZER_VERSION
        and metadata.transformation_version == TRANSFORMATION_VERSION
    )


def categorize_source_changes(
    kb_path: Path,
    metadata: IndexMetadata | None,
    *,
    config: Settings | None = None,
) -> SourceChangeSet:
    """Categorize visible source files against the recorded inventory.

    Returns categorized relative paths and the up-to-date inventory ready to
    persist into refreshed metadata. When `metadata` is `None`, every visible
    file is reported as added.
    """
    prior_records = list(metadata.source_files) if metadata is not None else []
    current = collect_source_files(kb_path, prior=prior_records, config=config)
    recorded = {record.path: record for record in prior_records}

    unchanged: list[str] = []
    added: list[str] = []
    changed: list[str] = []
    seen_current: set[str] = set()

    for record in current:
        seen_current.add(record.path)
        previous = recorded.get(record.path)
        if previous is None:
            added.append(record.path)
            continue
        if previous.content_sha and previous.content_sha == record.content_sha:
            unchanged.append(record.path)
        else:
            changed.append(record.path)

    removed = sorted(path for path in recorded if path not in seen_current)

    return SourceChangeSet(
        unchanged=sorted(unchanged),
        added=sorted(added),
        changed=sorted(changed),
        removed=removed,
        inventory=current,
    )
