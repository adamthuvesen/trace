"""Document content extractors."""

from __future__ import annotations

import re
from pathlib import Path

CODE_EXTENSIONS = frozenset({".sql", ".py", ".ts", ".tsx", ".yml", ".yaml"})
SUPPORTED_EXTENSIONS = CODE_EXTENSIONS | {".md"}


def extract_title(content: str, path: Path, fallback: str = "") -> str:
    """Extract title from file with fallback strategies.

    ``fallback`` (e.g. a frontmatter title) is used before the file stem when
    the document has no heading of its own.
    """
    ext = path.suffix.lower()
    if ext in CODE_EXTENSIONS:
        return path.name
    if ext == ".md":
        match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        if match:
            return match.group(1).strip()
        return fallback or path.stem
    return path.stem


def extract_content(path: Path) -> str:
    """Read a supported Markdown or code file as UTF-8 text.

    Raises:
        ValueError: If file type is not supported.
    """
    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {ext}")
    return path.read_text(encoding="utf-8")
