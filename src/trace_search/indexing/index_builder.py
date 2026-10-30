"""Build and serve the BM25 + embedding index for one local knowledge base."""

from __future__ import annotations

import hashlib
import logging
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict, cast

import numpy as np

from trace_search.config import Settings
from trace_search.extraction.chunking import (
    chunk_by_headings,
    create_contextual_chunk,
    extract_breadcrumb,
)
from trace_search.extraction.extractors import (
    SUPPORTED_EXTENSIONS,
    extract_content,
    extract_title,
)
from trace_search.extraction.frontmatter import Frontmatter, split_frontmatter
from trace_search.indexing.embeddings import (
    EmbeddingArray,
    EmbeddingBackend,
)
from trace_search.indexing.index_metadata import (
    SourceFileRecord,
    build_index_metadata,
    categorize_source_changes,
    metadata_matches_settings,
    utc_now_iso,
)
from trace_search.indexing.index_paths import chunk_id
from trace_search.indexing.index_reader import IndexReader
from trace_search.indexing.index_store import (
    ChunkMetadata,
    IndexCorruptError,
    IndexSnapshot,
    write_snapshot,
    writer_lock,
)
from trace_search.indexing.kb_paths import should_exclude_path

logger = logging.getLogger(__name__)

BackendProvider = Callable[[], EmbeddingBackend]


class LoadedDocument(TypedDict):
    path: str
    title: str
    folder: str
    extension: str
    mtime: float
    content: str
    frontmatter: Frontmatter


@dataclass(frozen=True)
class CapturedDocument:
    document: LoadedDocument


@dataclass(frozen=True)
class EmptySource:
    path: Path


@dataclass(frozen=True)
class ExcludedSource:
    path: Path


def _document_card(doc: LoadedDocument) -> tuple[str, str]:
    """Return (aliases, lead text) for a document's first chunk.

    The lead puts a page's alternate names and summary where both BM25 and the
    embedding see them, instead of burying them in raw YAML.
    """
    meta = doc["frontmatter"]
    title_key = doc["title"].casefold()
    names = [name for name in (meta.title, *meta.aliases) if name and name.casefold() != title_key]
    aliases = "; ".join(dict.fromkeys(names))
    lead = ""
    if aliases:
        lead += f"Also known as: {aliases}\n"
    if meta.summary:
        lead += f"Summary: {meta.summary}\n"
    return aliases, lead


class IndexBuilder:
    """Capture sources and publish complete generations under one writer lock."""

    def __init__(self, reader: IndexReader, backend: BackendProvider, config: Settings):
        self.reader = reader
        self.kb_path = reader.kb_path
        self.index_root = reader.index_root
        self._backend_provider = backend
        self.config = config

    @property
    def backend(self) -> EmbeddingBackend:
        return self._backend_provider()

    def _get_relative_path(self, path: Path) -> str:
        return str(path.relative_to(self.kb_path))

    def _get_folder(self, path: Path) -> str:
        rel = path.relative_to(self.kb_path)
        parts = rel.parts
        return parts[0] if len(parts) > 1 else ""

    def capture_source(
        self, file_path: Path, record: SourceFileRecord | None = None
    ) -> CapturedDocument | EmptySource | ExcludedSource:
        """Distinguish visible content, valid empty sources, exclusions, and failures."""
        ext = file_path.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            return ExcludedSource(file_path)
        if should_exclude_path(file_path, self.kb_path, self.config.exclude_patterns_list):
            return ExcludedSource(file_path)

        before = file_path.stat()
        captured = file_path.read_bytes()
        digest = hashlib.sha256(captured).hexdigest()
        if record is not None and (
            digest != record.content_sha
            or before.st_mtime != record.mtime
            or len(captured) != record.size
        ):
            raise RuntimeError(f"Source changed during capture: {file_path}. Retry reindex.")
        try:
            with tempfile.TemporaryDirectory(prefix="trace-source-") as temp:
                source = Path(temp) / file_path.name
                source.write_bytes(captured)
                content = extract_content(source)
        except Exception as exc:
            raise RuntimeError(f"Failed to extract {file_path}: {exc}") from exc
        after = file_path.stat()
        if (before.st_mtime_ns, before.st_ctime_ns, before.st_size, before.st_ino) != (
            after.st_mtime_ns,
            after.st_ctime_ns,
            after.st_size,
            after.st_ino,
        ):
            raise RuntimeError(f"Source changed during extraction: {file_path}. Retry reindex.")

        if not content.strip():
            return EmptySource(file_path)

        frontmatter, body = split_frontmatter(content) if ext == ".md" else (Frontmatter(), content)
        stat = before
        return CapturedDocument(
            {
                "path": self._get_relative_path(file_path),
                "title": extract_title(body, file_path, fallback=frontmatter.title),
                "folder": self._get_folder(file_path),
                "extension": ext,
                "mtime": stat.st_mtime,
                "content": body,
                "frontmatter": frontmatter,
            }
        )

    def _load_documents_subset(
        self, relative_paths: list[str], inventory: list[SourceFileRecord] | None = None
    ) -> list[LoadedDocument]:
        """Load only the listed relative paths into doc dicts."""
        docs: list[LoadedDocument] = []
        records = {record.path: record for record in (inventory or [])}
        for rel in relative_paths:
            file_path = self.kb_path / rel
            if not file_path.is_file():
                raise RuntimeError(
                    f"Source disappeared during capture: {file_path}. Retry reindex."
                )
            capture = self.capture_source(file_path, records.get(rel))
            if isinstance(capture, CapturedDocument):
                docs.append(capture.document)
        docs.sort(key=lambda d: d["path"])
        return docs

    def _build_chunks(
        self, docs: list[LoadedDocument]
    ) -> tuple[list[str], list[str], list[ChunkMetadata]]:
        """Convert documents into (ids, texts, chunk metadata) ready for indexing."""
        ids: list[str] = []
        texts: list[str] = []
        chunks: list[ChunkMetadata] = []

        for doc in docs:
            pieces = (
                chunk_by_headings(
                    doc["content"],
                    self.config.char_chunk_size,
                    overlap_chars=self.config.char_overlap_size,
                )
                if doc["content"].strip()
                else []
            )
            aliases, lead = _document_card(doc)
            if not pieces:
                pieces = [""]
            frontmatter = doc["frontmatter"]
            for i, piece in enumerate(pieces):
                ids.append(chunk_id(doc["path"], i))
                texts.append(
                    create_contextual_chunk(
                        doc["title"], doc["folder"], piece, lead=lead if i == 0 else ""
                    )
                )
                chunk: ChunkMetadata = {
                    "path": doc["path"],
                    "title": doc["title"],
                    "folder": doc["folder"],
                    "chunk_index": i,
                    "chunk_count": len(pieces),
                    "breadcrumb": extract_breadcrumb(piece, doc["title"]),
                    "extension": doc["extension"],
                    "source_mtime": float(doc["mtime"]),
                }
                if aliases:
                    chunk["aliases"] = aliases
                if frontmatter.status:
                    chunk["status"] = frontmatter.status
                if frontmatter.as_of:
                    chunk["as_of"] = frontmatter.as_of
                chunks.append(chunk)

        return ids, texts, chunks

    def _reusable_snapshot(self) -> IndexSnapshot | None:
        """The on-disk generation, when its chunks can be reused incrementally."""
        try:
            current = self.reader.snapshot()
        except IndexCorruptError as exc:
            logger.warning("%s Rebuilding from scratch.", exc)
            return None
        if current.generation is None:
            return None
        if current.metadata is None:
            logger.info("Index metadata missing or outdated; running a full rebuild")
            return None
        if not metadata_matches_settings(current.metadata, self.config, self.backend):
            logger.info("Index was built with other model or chunk settings; rebuilding")
            return None
        return current

    def _encode(self, texts: list[str], dim: int) -> EmbeddingArray:
        if not texts:
            return np.empty((0, dim), dtype=np.float32)
        logger.info("Embedding %d chunks...", len(texts))
        result = self.backend.encode(texts)
        if result.shape != (len(texts), self.backend.dim) or not np.isfinite(result).all():
            raise ValueError("Embedding backend returned invalid dimensions or non-finite vectors")
        return result

    def build_index(self, force: bool = False) -> int:
        """Build or update the index and return its chunk count.

        Incremental by default: unchanged files keep their chunks and
        embeddings, and only added or changed files are re-extracted and
        re-embedded. ``force=True`` rebuilds every file. Either way the result
        is published as a new generation under the writer lock, so a failed
        build leaves the previous index serving.
        """
        with writer_lock(self.index_root):
            build_started_at = utc_now_iso()
            current = None if force else self._reusable_snapshot()
            changes = categorize_source_changes(
                self.kb_path,
                current.metadata if current is not None else None,
                config=self.config,
            )
            if (
                current is not None
                and not changes.has_changes
                and current.metadata is not None
                and list(current.metadata.source_files) == changes.inventory
            ):
                logger.info(
                    "Index up to date: %d files, %d chunks",
                    len(changes.unchanged),
                    len(current),
                )
                return len(current)

            if current is not None:
                unchanged = set(changes.unchanged)
                kept = [
                    row for row, chunk in enumerate(current.chunks) if chunk["path"] in unchanged
                ]
                to_index = changes.added + changes.changed
            else:
                kept = []
                to_index = [record.path for record in changes.inventory]

            new_ids, new_texts, new_chunks = self._build_chunks(
                self._load_documents_subset(to_index, changes.inventory)
            )
            reused_dim = current.embeddings.shape[1] if current is not None else self.backend.dim
            new_embeddings = self._encode(new_texts, reused_dim)

            ids = [current.chunk_ids[row] for row in kept] if current else []
            texts = [current.texts[row] for row in kept] if current else []
            mtimes = {record.path: record.mtime for record in changes.inventory}
            chunks: list[ChunkMetadata] = (
                [
                    cast(
                        ChunkMetadata,
                        dict(
                            current.chunks[row],
                            source_mtime=mtimes[current.chunks[row]["path"]],
                        ),
                    )
                    for row in kept
                ]
                if current
                else []
            )
            ids += new_ids
            texts += new_texts
            chunks += new_chunks
            if current is not None and kept and new_texts:
                embeddings = np.vstack([current.embeddings[kept], new_embeddings])
            elif current is not None and kept:
                embeddings = current.embeddings[kept]
            else:
                embeddings = new_embeddings

            order = sorted(
                range(len(ids)),
                key=lambda row: (chunks[row]["path"], chunks[row]["chunk_index"]),
            )
            snapshot = IndexSnapshot.build(
                chunk_ids=[ids[row] for row in order],
                texts=[texts[row] for row in order],
                chunks=[chunks[row] for row in order],
                embeddings=embeddings[order] if len(order) else embeddings,
                k1=self.config.bm25_k1,
                b=self.config.bm25_b,
                metadata=build_index_metadata(
                    kb_path=self.kb_path,
                    build_started_at=build_started_at,
                    build_completed_at=utc_now_iso(),
                    document_count=len({chunk["path"] for chunk in chunks}),
                    chunk_count=len(ids),
                    source_files=changes.inventory,
                    config=self.config,
                    backend=self.backend,
                ),
            )
            published = write_snapshot(self.index_root, snapshot)
            self.reader.install(published)

        logger.info(
            "Reindex (%s): +%d added, ~%d changed, -%d removed, =%d unchanged; %d chunks total",
            "incremental" if current is not None else "full",
            len(changes.added),
            len(changes.changed),
            len(changes.removed),
            len(changes.unchanged),
            len(published),
        )
        return len(published)
