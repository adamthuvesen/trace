"""Frontmatter parsing and the ranking signals it feeds: names, aliases, status."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_runtime_hardening import FakeBackend
from trace_search.extraction.frontmatter import Frontmatter, split_frontmatter
from trace_search.indexing.wiki_indexer import WikiIndexer
from trace_search.retrieval.search import KeywordSearch

WIKI_PAGE = """---
title: Internal tools overview
summary: "The team's internal tools: pipelines and apps."
aliases:
  - internal tools
  - hobby builds
as_of: 2026-08-04
status: current
sources:
  - Drive export zebra-quagga-unique-token, read in full
---

# Internal tools — overview

Inventory of repositories.
"""


class TestSplitFrontmatter:
    def test_wiki_keys_are_parsed_and_body_starts_after_block(self):
        meta, body = split_frontmatter(WIKI_PAGE)

        assert meta == Frontmatter(
            title="Internal tools overview",
            summary="The team's internal tools: pipelines and apps.",
            aliases=("internal tools", "hobby builds"),
            status="current",
            as_of="2026-08-04",
        )
        assert body.lstrip().startswith("# Internal tools — overview")
        assert "sources" not in body

    def test_skill_style_name_and_description_are_accepted(self):
        meta, _ = split_frontmatter(
            "---\nname: ARR Guide\ndescription: Pick the ARR metric.\n---\n# ARR\n"
        )
        assert (meta.title, meta.summary) == ("ARR Guide", "Pick the ARR metric.")

    @pytest.mark.parametrize(
        "content",
        [
            "# No frontmatter\n\ntext",
            "---\n: [unbalanced\n---\n# Broken YAML",
            "---\n- just\n- a list\n---\n# Not a mapping",
        ],
    )
    def test_content_without_a_usable_block_is_returned_unchanged(self, content):
        meta, body = split_frontmatter(content)
        assert meta == Frontmatter()
        assert body == content


# BM25 IDF and weak-hit abstention need a corpus bigger than the two pages
# under test to behave as they do on a real knowledge base.
_FILLER = {
    f"misc/note-{i}.md": f"# Note {i}\n\nMeeting notes about topic {i} and plans."
    for i in range(8)
}


def _index(tmp_path: Path, pages: dict[str, str]) -> WikiIndexer:
    kb = tmp_path / "kb"
    for rel, text in {**_FILLER, **pages}.items():
        path = kb / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    indexer = WikiIndexer(kb, index_root=tmp_path / "idx", backend=FakeBackend())
    indexer.build_index()
    return indexer


def test_card_replaces_raw_yaml_in_the_indexed_text(tmp_path):
    indexer = _index(tmp_path, {"repos/index.md": WIKI_PAGE})
    snapshot = indexer.snapshot()
    row = snapshot.row_by_id["repos/index.md::0"]
    first = snapshot.texts[row]

    assert (
        "Also known as: Internal tools overview; internal tools; hobby builds" in first
    )
    assert "Summary: The team's internal tools" in first
    assert "zebra-quagga-unique-token" not in " ".join(snapshot.texts)
    assert snapshot.chunks[row]["status"] == "current"
    assert snapshot.chunks[row]["as_of"] == "2026-08-04"
    assert not KeywordSearch(indexer).search("zebra quagga")


def test_query_naming_a_hub_by_alias_beats_pages_repeating_its_words(tmp_path):
    # The hub is index.md (normally demoted) and says "hobby builds" once; the
    # person page repeats both words. A query that is the hub's alias names it.
    person = "# Rowan\n\n## Builds\n\n" + "Rowan has hobby builds. " * 6
    indexer = _index(tmp_path, {"repos/index.md": WIKI_PAGE, "people/rowan.md": person})

    hits = KeywordSearch(indexer).search("hobby builds", max_results=2)

    assert [hit["path"] for hit in hits] == ["repos/index.md", "people/rowan.md"]


def test_superseded_page_ranks_below_its_replacement_but_stays_findable(tmp_path):
    old = (
        "---\ntitle: Checklist 2024\nstatus: superseded\n---\n"
        "# Checklist 2024\n\nOnboarding checklist, onboarding checklist.\n"
    )
    new = (
        "# Onboarding playbook (successor to onboarding checklist)\n\n"
        "Replaces the onboarding checklist project.\n"
    )
    indexer = _index(tmp_path, {"old.md": old, "new.md": new})

    hits = KeywordSearch(indexer).search("onboarding checklist", max_results=5)

    assert [hit["path"] for hit in hits] == ["new.md", "old.md"]
    assert hits[1]["status"] == "superseded"
