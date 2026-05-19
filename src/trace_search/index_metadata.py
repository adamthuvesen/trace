"""Versioned metadata for Trace search indexes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trace_search.config import settings
from trace_search.indexer import SUPPORTED_EXTENSIONS, should_exclude_path

INDEX_METADATA_VERSION = 2
INDEX_METADATA_FILENAME = "index_metadata.json"

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
    embedding_backend: str
    document_count: int
    chunk_count: int
    source_files: list[SourceFileRecord]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable metadata dictionary."""
        return asdict(self)


def utc_now_iso() -> str:
    """Return a stable UTC timestamp string."""
    return datetime.now(UTC).isoformat()


def metadata_path(index_root: Path) -> Path:
    """Return the metadata path for an index root."""
    return index_root / INDEX_METADATA_FILENAME


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
    for file_path in kb_path.rglob("*"):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        if should_exclude_path(file_path, kb_path):
            continue
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
) -> IndexMetadata:
    """Create metadata for the active settings and source tree.

    If `source_files` is supplied (e.g. computed earlier during an incremental
    rebuild) it is used verbatim; otherwise files are rescanned and hashed.
    """
    if source_files is None:
        source_files = collect_source_files(kb_path)
    return IndexMetadata(
        version=INDEX_METADATA_VERSION,
        build_started_at=build_started_at,
        build_completed_at=build_completed_at,
        embedding_model=settings.embedding_model,
        model_slug=settings.model_slug,
        embedding_dims=settings.embedding_dims,
        embedding_backend=settings.embedding_backend,
        document_count=document_count,
        chunk_count=chunk_count,
        source_files=source_files,
        warnings=warnings or [],
    )


def write_index_metadata(index_root: Path, metadata: IndexMetadata) -> None:
    """Persist metadata under the collection index root."""
    index_root.mkdir(parents=True, exist_ok=True)
    metadata_path(index_root).write_text(
        json.dumps(metadata.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def invalidate_index_metadata(index_root: Path) -> None:
    """Remove metadata to force a full rebuild on the next reindex."""
    path = metadata_path(index_root)
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def read_index_metadata(index_root: Path) -> IndexMetadata | None:
    """Read index metadata, returning None when absent, unreadable, or outdated.

    Metadata written by an older schema version is treated as missing so the
    caller forces a full rebuild and writes fresh v2 metadata.
    """
    path = metadata_path(index_root)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        version = int(raw.get("version", 0))
        if version != INDEX_METADATA_VERSION:
            return None
        return IndexMetadata(
            version=version,
            build_started_at=str(raw.get("build_started_at", "")),
            build_completed_at=str(raw.get("build_completed_at", "")),
            embedding_model=str(raw.get("embedding_model", "")),
            model_slug=str(raw.get("model_slug", "")),
            embedding_dims=int(raw.get("embedding_dims", 0)),
            embedding_backend=str(raw.get("embedding_backend", "")),
            document_count=int(raw.get("document_count", 0)),
            chunk_count=int(raw.get("chunk_count", 0)),
            source_files=[
                SourceFileRecord(
                    path=str(item.get("path", "")),
                    extension=str(item.get("extension", "")),
                    mtime=float(item.get("mtime", 0)),
                    size=int(item.get("size", 0)),
                    content_sha=str(item.get("content_sha", "")),
                )
                for item in raw.get("source_files", [])
                if isinstance(item, dict)
            ],
            warnings=[
                str(warning)
                for warning in raw.get("warnings", [])
                if isinstance(warning, str)
            ],
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def metadata_matches_active_model(metadata: IndexMetadata) -> bool:
    """Return whether metadata matches the active embedding settings."""
    return (
        metadata.embedding_model == settings.embedding_model
        and metadata.model_slug == settings.model_slug
        and metadata.embedding_dims == settings.embedding_dims
        and metadata.embedding_backend == settings.embedding_backend
    )


def categorize_source_changes(
    kb_path: Path,
    metadata: IndexMetadata | None,
) -> SourceChangeSet:
    """Categorize visible source files against the recorded inventory.

    Returns categorized relative paths and the up-to-date inventory ready to
    persist into refreshed metadata. When `metadata` is `None`, every visible
    file is reported as added.
    """
    prior_records = list(metadata.source_files) if metadata is not None else []
    current = collect_source_files(kb_path, prior=prior_records)
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


def stale_source_paths(kb_path: Path, metadata: IndexMetadata) -> list[str]:
    """Return visible source paths that are new, changed, or removed since indexing.

    Thin compatibility wrapper over `categorize_source_changes` for callers that
    just want a flat list of paths needing attention.
    """
    changes = categorize_source_changes(kb_path, metadata)
    return sorted(set(changes.added + changes.changed + changes.removed))
