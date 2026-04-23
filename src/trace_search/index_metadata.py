"""Versioned metadata for Trace search indexes."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trace_search.config import settings
from trace_search.indexer import SUPPORTED_EXTENSIONS, should_exclude_path

INDEX_METADATA_VERSION = 1
INDEX_METADATA_FILENAME = "index_metadata.json"


@dataclass(frozen=True)
class SourceFileRecord:
    """A source file captured at index-build time."""

    path: str
    extension: str
    mtime: float
    size: int


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


def collect_source_files(kb_path: Path) -> list[SourceFileRecord]:
    """Collect visible supported source files for freshness checks."""
    records: list[SourceFileRecord] = []
    for file_path in kb_path.rglob("*"):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        if should_exclude_path(file_path, kb_path):
            continue
        stat = file_path.stat()
        records.append(
            SourceFileRecord(
                path=str(file_path.relative_to(kb_path)),
                extension=file_path.suffix.lower(),
                mtime=stat.st_mtime,
                size=stat.st_size,
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
) -> IndexMetadata:
    """Create metadata for the active settings and source tree."""
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
        source_files=collect_source_files(kb_path),
        warnings=warnings or [],
    )


def write_index_metadata(index_root: Path, metadata: IndexMetadata) -> None:
    """Persist metadata under the collection index root."""
    index_root.mkdir(parents=True, exist_ok=True)
    metadata_path(index_root).write_text(
        json.dumps(metadata.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def read_index_metadata(index_root: Path) -> IndexMetadata | None:
    """Read index metadata, returning None when it is absent or unreadable."""
    path = metadata_path(index_root)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return IndexMetadata(
            version=int(raw.get("version", 0)),
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


def stale_source_paths(kb_path: Path, metadata: IndexMetadata) -> list[str]:
    """Return visible source paths that are new, changed, or removed since indexing."""
    current = {record.path: record for record in collect_source_files(kb_path)}
    recorded = {record.path: record for record in metadata.source_files}
    stale: list[str] = []

    for path, record in current.items():
        previous = recorded.get(path)
        if previous is None:
            stale.append(path)
            continue
        if record.mtime > previous.mtime or record.size != previous.size:
            stale.append(path)

    for path in recorded:
        if path not in current:
            stale.append(path)

    return sorted(set(stale))
