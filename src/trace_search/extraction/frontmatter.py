"""YAML frontmatter: split it from Markdown and keep the fields that help ranking."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import yaml

logger = logging.getLogger(__name__)

_FRONTMATTER = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.DOTALL)


@dataclass(frozen=True)
class Frontmatter:
    """Ranking-relevant frontmatter fields; everything else stays out of the index.

    Long metadata such as `sources:` lists would otherwise land in the first
    chunk as body text and dilute the page's real vocabulary.
    """

    title: str = ""
    summary: str = ""
    aliases: tuple[str, ...] = ()
    status: str = ""
    as_of: str = ""


def _text(value: object) -> str:
    return " ".join(str(value).split()) if value is not None else ""


def _names(value: object) -> tuple[str, ...]:
    items = value if isinstance(value, list) else [value]
    return tuple(name for item in items if (name := _text(item)))


def split_frontmatter(content: str) -> tuple[Frontmatter, str]:
    """Return the parsed frontmatter and the body that follows it.

    Accepts both wiki-style keys (`title`, `summary`, `aliases`) and skill-style
    keys (`name`, `description`). Content without a frontmatter block, or with
    one that is not a YAML mapping, is returned unchanged with empty fields.
    """
    match = _FRONTMATTER.match(content)
    if match is None:
        return Frontmatter(), content
    try:
        raw = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        logger.warning("Ignoring unparseable frontmatter: %s", exc)
        return Frontmatter(), content
    if not isinstance(raw, dict):
        return Frontmatter(), content

    body = content[match.end() :]
    return (
        Frontmatter(
            title=_text(raw.get("title") or raw.get("name")),
            summary=_text(raw.get("summary") or raw.get("description")),
            aliases=_names(raw.get("aliases") or []),
            status=_text(raw.get("status")).lower(),
            as_of=_text(raw.get("as_of")),
        ),
        body,
    )
