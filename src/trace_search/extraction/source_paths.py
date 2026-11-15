from __future__ import annotations

import os
import unicodedata
from functools import lru_cache
from pathlib import Path

from pathspec import GitIgnoreSpec

from trace_search.config import get_settings

TRACEIGNORE_FILENAME = ".traceignore"


def _relative_parts(kb_path: Path, path: Path) -> tuple[str, ...]:
    """Return path parts relative to the KB root, resolving only when needed."""
    try:
        return path.relative_to(kb_path).parts
    except ValueError:
        return path.resolve().relative_to(kb_path.resolve()).parts


def _is_within_root(path: Path, root: Path) -> bool:
    """Return whether the resolved path stays under the resolved root."""
    try:
        return path.resolve().is_relative_to(root.resolve())
    except OSError:
        return False


@lru_cache(maxsize=32)
def _parse_traceignore(ignore_file: Path, mtime_ns: int) -> GitIgnoreSpec:
    """Parse an ignore file; ``mtime_ns`` is part of the key so edits reload."""
    lines = ignore_file.read_text(encoding="utf-8").splitlines()
    return GitIgnoreSpec.from_lines(lines)


def load_traceignore(kb_path: Path) -> GitIgnoreSpec | None:
    """Return the KB root's ``.traceignore`` spec, or None when there is none."""
    ignore_file = kb_path / TRACEIGNORE_FILENAME
    try:
        mtime_ns = ignore_file.stat().st_mtime_ns
    except FileNotFoundError:
        return None
    return _parse_traceignore(ignore_file, mtime_ns)


def is_traceignored(path: Path, kb_path: Path) -> bool:
    """Return whether the KB's ``.traceignore`` (gitignore semantics) skips path."""
    spec = load_traceignore(kb_path)
    if spec is None:
        return False
    return spec.match_file("/".join(_relative_parts(kb_path, path)))


def is_traceignored_directory(path: Path, kb_path: Path) -> bool:
    """Prune ignored trees unless a later negation can include a descendant."""
    spec = load_traceignore(kb_path)
    if spec is None:
        return False
    relative = "/".join(_relative_parts(kb_path, path))
    result = spec.check_file(relative + "/")
    if not result.include or result.index is None:
        return False
    for pattern in spec.patterns[result.index + 1 :]:
        if pattern.include is not False or not isinstance(pattern.pattern, str):
            continue
        text = pattern.pattern.removeprefix("!")
        if "\\" in text or not (text.startswith("/") or "/" in text.rstrip("/")):
            return False
        prefix: list[str] = []
        for part in text.lstrip("/").split("/"):
            if not part or any(mark in part for mark in "*?["):
                break
            prefix.append(part)
        literal = "/".join(prefix)
        if (
            not literal
            or relative == literal
            or relative.startswith(literal + "/")
            or literal.startswith(relative + "/")
        ):
            return False
    return True


def actual_path_spelling(path: Path, kb_path: Path) -> Path:
    """Recover existing entry names without conflating distinct hard links."""
    try:
        parts = path.relative_to(kb_path).parts
    except ValueError:
        return path
    if ".." in parts:
        return path
    current = kb_path
    for part in parts:
        candidate = current / part
        try:
            requested = candidate.lstat()
        except FileNotFoundError:
            return path
        with os.scandir(current) as entries:
            children = list(entries)
        exact = next((entry for entry in children if entry.name == part), None)
        if exact is not None:
            current /= exact.name
            continue
        matches = []
        for entry in children:
            identity = entry.stat(follow_symlinks=False)
            if (identity.st_dev, identity.st_ino) == (
                requested.st_dev,
                requested.st_ino,
            ):
                matches.append(entry)
        folded = unicodedata.normalize("NFC", part).casefold()
        aliases = [
            entry
            for entry in matches
            if unicodedata.normalize("NFC", entry.name).casefold() == folded
        ]
        if len(aliases) == 1:
            current /= aliases[0].name
        elif len(matches) == 1:
            current /= matches[0].name
        else:
            raise ValueError(f"Cannot identify the actual path spelling: {candidate}")
    return current


def should_exclude_path(
    path: Path,
    kb_path: Path,
    exclude_patterns: list[str] | None = None,
) -> bool:
    """Return whether a KB-relative path should be skipped."""
    if not _is_within_root(path, kb_path):
        return True
    exclude = set(
        exclude_patterns if exclude_patterns is not None else get_settings().exclude_patterns_list
    )
    resolved = path.resolve()
    if resolved != path:
        resolved = actual_path_spelling(resolved, kb_path)
    if any(
        part.startswith(".") or part in exclude
        for candidate in (path, resolved)
        for part in _relative_parts(kb_path, candidate)
    ):
        return True
    return is_traceignored(path, kb_path) or is_traceignored(resolved, kb_path)
