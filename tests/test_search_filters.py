"""Tests for search filter parsing and application."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests.test_runtime_hardening import FakeBackend
from trace_search.indexing.wiki_indexer import WikiIndexer
from trace_search.retrieval.search import (
    HybridSearch,
    KeywordSearch,
    SearchFilters,
    SemanticSearch,
    AdaptiveSearch,
    apply_filters_to_hits,
    filters_to_chroma_where,
    parse_filters,
)


class TestParseFilters:
    def test_empty_inputs_produce_empty_filter(self):
        filters = parse_filters()
        assert filters.is_empty
        assert filters.describe() == ""

    def test_path_prefix_string_becomes_single_tuple(self):
        filters = parse_filters(path_prefix="architecture/")
        assert filters.path_prefix == ("architecture/",)

    def test_path_prefix_list_preserved(self):
        filters = parse_filters(path_prefix=["a/", "b/"])
        assert filters.path_prefix == ("a/", "b/")

    def test_path_prefix_drops_empty_entries(self):
        filters = parse_filters(path_prefix=["a/", "", "b/"])
        assert filters.path_prefix == ("a/", "b/")

    def test_extensions_normalize_dot_and_case(self):
        filters = parse_filters(extensions=["md", ".PY", "TSX"])
        assert filters.extensions == (".md", ".py", ".tsx")

    def test_extensions_comma_separated_string(self):
        filters = parse_filters(extensions="md, py, tsx")
        assert filters.extensions == (".md", ".py", ".tsx")

    def test_extensions_list_allows_comma_separated_entries(self):
        filters = parse_filters(extensions=["md, py", "tsx"])
        assert filters.extensions == (".md", ".py", ".tsx")

    def test_empty_extension_entry_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            parse_filters(extensions=["   "])

    def test_empty_comma_separated_extension_entry_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            parse_filters(extensions="md,,py")

    def test_since_iso_string_parses_to_utc(self):
        filters = parse_filters(since="2026-01-01T00:00:00Z")
        assert filters.since == datetime(2026, 1, 1, tzinfo=UTC)

    def test_since_naive_iso_treated_as_utc(self):
        filters = parse_filters(since="2026-01-01T00:00:00")
        assert filters.since == datetime(2026, 1, 1, tzinfo=UTC)

    def test_since_invalid_string_raises(self):
        with pytest.raises(ValueError, match="ISO 8601"):
            parse_filters(since="yesterday")

    def test_since_datetime_pass_through_with_utc(self):
        dt = datetime(2026, 5, 1, 12, 30)
        filters = parse_filters(since=dt)
        assert filters.since == datetime(2026, 5, 1, 12, 30, tzinfo=UTC)

    def test_describe_renders_all_active_filters(self):
        filters = parse_filters(
            path_prefix=["rfcs/"],
            extensions=[".md"],
            since="2026-01-01T00:00:00Z",
        )
        rendered = filters.describe()
        assert "path_prefix=rfcs/" in rendered
        assert "extensions=.md" in rendered
        assert "since=2026-01-01T00:00:00" in rendered


class TestFiltersToChromaWhere:
    def test_empty_filters_return_none(self):
        assert filters_to_chroma_where(SearchFilters()) is None

    def test_single_extension_uses_eq_form(self):
        clause = filters_to_chroma_where(parse_filters(extensions=[".md"]))
        assert clause == {"extension": ".md"}

    def test_multiple_extensions_use_in_clause(self):
        clause = filters_to_chroma_where(parse_filters(extensions=[".md", ".py"]))
        assert clause == {"extension": {"$in": [".md", ".py"]}}

    def test_since_becomes_gte_on_source_mtime(self):
        clause = filters_to_chroma_where(parse_filters(since="2026-01-01T00:00:00Z"))
        assert clause is not None
        assert clause["source_mtime"] == {
            "$gte": datetime(2026, 1, 1, tzinfo=UTC).timestamp()
        }

    def test_path_prefix_alone_is_not_pushed_down(self):
        assert filters_to_chroma_where(parse_filters(path_prefix="a/")) is None

    def test_extensions_and_since_combine_with_and(self):
        clause = filters_to_chroma_where(
            parse_filters(extensions=[".md"], since="2026-01-01T00:00:00Z")
        )
        assert clause is not None
        assert "$and" in clause
        assert len(clause["$and"]) == 2


class TestMatchesRecord:
    def test_empty_filters_match_everything(self):
        filters = SearchFilters()
        assert filters.matches_record("any/path.md", ".md", 100.0)

    def test_path_prefix_and_extension_and_since(self):
        filters = parse_filters(
            path_prefix="rfcs/",
            extensions=[".md"],
            since=datetime.fromtimestamp(100.0, tz=UTC).isoformat(),
        )
        assert filters.matches_record("rfcs/a.md", ".md", 200.0)
        assert not filters.matches_record("architecture/a.md", ".md", 200.0)
        assert not filters.matches_record("rfcs/b.py", ".py", 200.0)
        assert not filters.matches_record("rfcs/old.md", ".md", 10.0)


class TestApplyFiltersToHits:
    def _hit(
        self,
        path="a.md",
        extension=".md",
        source_mtime=100.0,
    ) -> dict:
        return {
            "path": path,
            "extension": extension,
            "source_mtime": source_mtime,
        }

    def test_no_filters_returns_hits_unchanged(self):
        hits = [self._hit(), self._hit(path="b.md")]
        assert apply_filters_to_hits(hits, SearchFilters()) is hits

    def test_path_prefix_filters_by_start_match(self):
        hits = [
            self._hit(path="architecture/intro.md"),
            self._hit(path="rfcs/001.md"),
            self._hit(path="architecture/notes.md"),
        ]
        filtered = apply_filters_to_hits(
            hits, parse_filters(path_prefix="architecture/")
        )
        assert [h["path"] for h in filtered] == [
            "architecture/intro.md",
            "architecture/notes.md",
        ]

    def test_path_prefix_list_uses_or_semantics(self):
        hits = [
            self._hit(path="a/1.md"),
            self._hit(path="b/2.md"),
            self._hit(path="c/3.md"),
        ]
        filtered = apply_filters_to_hits(hits, parse_filters(path_prefix=["a/", "b/"]))
        assert [h["path"] for h in filtered] == ["a/1.md", "b/2.md"]

    def test_extensions_filter(self):
        hits = [
            self._hit(path="a.md", extension=".md"),
            self._hit(path="b.py", extension=".py"),
            self._hit(path="c.md", extension=".md"),
        ]
        filtered = apply_filters_to_hits(hits, parse_filters(extensions=[".md"]))
        assert [h["path"] for h in filtered] == ["a.md", "c.md"]

    def test_extension_falls_back_to_path_suffix_when_missing(self):
        hits = [{"path": "notes.md"}, {"path": "newer.py", "extension": ".py"}]
        filtered = apply_filters_to_hits(hits, parse_filters(extensions=[".md"]))
        assert [h["path"] for h in filtered] == ["notes.md"]

    def test_since_filter_uses_inclusive_lower_bound(self):
        hits = [
            self._hit(path="old.md", source_mtime=50.0),
            self._hit(path="exact.md", source_mtime=100.0),
            self._hit(path="new.md", source_mtime=200.0),
        ]
        cutoff = datetime.fromtimestamp(100.0, tz=UTC).isoformat()
        filtered = apply_filters_to_hits(hits, parse_filters(since=cutoff))
        assert [h["path"] for h in filtered] == ["exact.md", "new.md"]

    def test_missing_mtime_excluded_by_since_filter(self):
        hits = [{"path": "a.md"}, self._hit(path="b.md", source_mtime=500.0)]
        cutoff = datetime.fromtimestamp(100.0, tz=UTC).isoformat()
        filtered = apply_filters_to_hits(hits, parse_filters(since=cutoff))
        assert [h["path"] for h in filtered] == ["b.md"]

    def test_filters_combine_with_and_semantics(self):
        hits = [
            self._hit(path="rfcs/a.md", source_mtime=200.0),
            self._hit(path="rfcs/b.py", extension=".py", source_mtime=200.0),
            self._hit(path="architecture/c.md", source_mtime=200.0),
            self._hit(path="rfcs/old.md", source_mtime=10.0),
        ]
        filters = parse_filters(
            path_prefix="rfcs/",
            extensions=[".md"],
            since=datetime.fromtimestamp(100.0, tz=UTC).isoformat(),
        )
        filtered = apply_filters_to_hits(hits, filters)
        assert [h["path"] for h in filtered] == ["rfcs/a.md"]


@pytest.fixture
def filter_kb(tmp_path: Path) -> tuple[WikiIndexer, Path]:
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "architecture").mkdir()
    (kb / "rfcs").mkdir()
    (kb / "architecture" / "intro.md").write_text(
        "# Architecture intro\n\nrouter handles traffic", encoding="utf-8"
    )
    (kb / "architecture" / "notes.md").write_text(
        "# Architecture notes\n\nrouter scales horizontally", encoding="utf-8"
    )
    (kb / "rfcs" / "001.md").write_text(
        "# RFC 001\n\nrouter behavior change", encoding="utf-8"
    )
    (kb / "rfcs" / "002.py").write_text(
        '"""router config."""\n\ndef build():\n    pass\n', encoding="utf-8"
    )
    indexer = WikiIndexer(
        kb_path=kb,
        chroma_path=tmp_path / "chroma",
        bm25_path=tmp_path / "bm25",
        backend=FakeBackend(),
    )
    indexer.build_index(force=True)
    return indexer, kb


class TestKeywordSearchFilters:
    def test_path_prefix_scopes_keyword_search(self, filter_kb):
        indexer, _ = filter_kb
        searcher = KeywordSearch(indexer)
        filters = parse_filters(path_prefix="architecture/")
        hits = searcher.search("router", max_results=10, filters=filters)
        assert hits
        assert all(h["path"].startswith("architecture/") for h in hits)

    def test_extension_scopes_keyword_search(self, filter_kb):
        indexer, _ = filter_kb
        searcher = KeywordSearch(indexer)
        filters = parse_filters(extensions=[".py"])
        hits = searcher.search("router", max_results=10, filters=filters)
        assert hits
        assert all(h["path"].endswith(".py") for h in hits)


class TestSemanticSearchFilters:
    def test_extension_push_down(self, filter_kb):
        indexer, _ = filter_kb
        searcher = SemanticSearch(indexer.collection, indexer.backend)
        filters = parse_filters(extensions=[".md"])
        hits = searcher.search("router", top_k=10, filters=filters)
        assert hits
        assert all(h["path"].endswith(".md") for h in hits)

    def test_path_prefix_post_filter(self, filter_kb):
        indexer, _ = filter_kb
        searcher = SemanticSearch(indexer.collection, indexer.backend)
        filters = parse_filters(path_prefix="rfcs/")
        hits = searcher.search("router", top_k=10, filters=filters)
        assert hits
        assert all(h["path"].startswith("rfcs/") for h in hits)


class TestHybridSearchFilters:
    def test_path_prefix_applies_to_hybrid(self, filter_kb):
        indexer, _ = filter_kb
        searcher = HybridSearch(indexer, indexer.backend)
        filters = parse_filters(path_prefix="architecture/")
        hits = searcher.search("router", top_k=10, filters=filters)
        assert hits
        assert all(h["path"].startswith("architecture/") for h in hits)


class TestAdaptiveSearchFilters:
    def test_route_reports_active_filters(self, filter_kb):
        indexer, _ = filter_kb
        searcher = AdaptiveSearch(indexer, indexer.backend)
        filters = parse_filters(path_prefix="architecture/")
        result = searcher.search("router", top_k=5, filters=filters)
        assert result.route.filters.path_prefix == ("architecture/",)
        assert all(h["path"].startswith("architecture/") for h in result.hits)

    def test_default_search_has_empty_route_filters(self, filter_kb):
        indexer, _ = filter_kb
        searcher = AdaptiveSearch(indexer, indexer.backend)
        result = searcher.search("router", top_k=5)
        assert result.route.filters.is_empty
