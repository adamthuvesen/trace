"""Document listing helpers for collections."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from trace_search.extraction.corpus import iter_kb_files
from trace_search.extraction.extractors import extract_title
from trace_search.retrieval.search import SearchFilters

DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 500


@dataclass(frozen=True)
class ListedDocument:
    """Small render-ready document listing record."""

    title: str
    path: str
    folder: str
    collection: str | None = None

    @property
    def sort_key(self) -> tuple[str, str]:
        return self.collection or "", self.path

    def group_key(self, *, include_collection: bool) -> str:
        folder = self.folder or "(root)"
        if include_collection and self.collection:
            return f"{self.collection}/{folder}"
        return folder


def _normalize_limit(limit: int) -> int:
    if limit < 1:
        limit = DEFAULT_LIST_LIMIT
    return min(limit, MAX_LIST_LIMIT)


def _resolve_folder_root(kb_path: Path, folder: str | None) -> Path | None:
    if not folder:
        return kb_path

    candidate = (kb_path / folder).resolve()
    if not candidate.is_relative_to(kb_path):
        return None
    if candidate.exists():
        return candidate

    for directory in sorted(kb_path.iterdir(), key=lambda path: path.name.lower()):
        if directory.is_dir() and directory.name.lower() == folder.lower():
            return directory
    return None


def _document_title(file_path: Path, ext: str) -> str:
    if ext != ".md":
        return file_path.stem

    try:
        content = file_path.read_text(encoding="utf-8")
        return extract_title(content, file_path)
    except Exception:
        return file_path.stem


def _list_collection_documents(
    *,
    name: str,
    kb_path: Path,
    folder: str | None,
    filters: SearchFilters,
    include_collection: bool,
) -> list[ListedDocument]:
    search_path = _resolve_folder_root(kb_path, folder)
    if search_path is None:
        return []

    documents: list[ListedDocument] = []
    for file_path in iter_kb_files(kb_path, root=search_path):
        ext = file_path.suffix.lower()
        rel_path = str(file_path.relative_to(kb_path))
        try:
            mtime = file_path.stat().st_mtime
        except OSError:
            continue
        if not filters.matches_record(rel_path, ext, mtime):
            continue

        path_parts = rel_path.split("/")
        doc_folder = path_parts[0] if len(path_parts) > 1 else ""
        documents.append(
            ListedDocument(
                title=_document_title(file_path, ext),
                path=rel_path,
                folder=doc_folder,
                collection=name if include_collection else None,
            )
        )
    return documents


def render_document_list(
    documents: list[ListedDocument],
    *,
    folder: str | None,
    include_collection: bool,
) -> str:
    """Render collection document listings as Markdown."""
    if not documents:
        return "No documents found."

    lines = [
        f"Found {len(documents)} documents"
        + (f" in {folder}" if folder else "")
        + ":\n"
    ]
    by_folder: dict[str, list[ListedDocument]] = defaultdict(list)
    for document in documents:
        by_folder[document.group_key(include_collection=include_collection)].append(
            document
        )

    for folder_name, folder_documents in sorted(by_folder.items()):
        lines.append(f"\n## {folder_name}")
        for document in folder_documents:
            lines.append(f"- **{document.title}**: `{document.path}`")

    return "\n".join(lines)


def list_documents_for_collections(
    collections: list[tuple[str, Path]],
    *,
    folder: str | None,
    limit: int,
    filters: SearchFilters,
) -> str:
    """List documents across one or more collections."""
    include_collection = len(collections) > 1
    documents: list[ListedDocument] = []
    for name, kb_path in collections:
        documents.extend(
            _list_collection_documents(
                name=name,
                kb_path=kb_path.resolve(),
                folder=folder,
                filters=filters,
                include_collection=include_collection,
            )
        )

    limit = _normalize_limit(limit)
    documents = sorted(documents, key=lambda document: document.sort_key)[:limit]
    return render_document_list(
        documents,
        folder=folder,
        include_collection=include_collection,
    )
