"""Tests for multi-collection knowledge server."""

import pytest

from trace_search.config import Settings


class TestKBCollectionsParsing:
    def test_parse_two_collections(self, tmp_path, monkeypatch):
        monkeypatch.delenv("KB_PATH", raising=False)
        kb1 = tmp_path / "docs"
        kb2 = tmp_path / "ai-context"
        kb1.mkdir()
        kb2.mkdir()

        s = Settings(kb_collections=f"docs:{kb1},ai-context:{kb2}")
        result = s.parsed_collections
        assert set(result.keys()) == {"docs", "ai-context"}
        assert result["docs"] == kb1
        assert result["ai-context"] == kb2

    def test_fallback_to_kb_path(self, tmp_path):
        kb = tmp_path / "docs"
        kb.mkdir()

        s = Settings(kb_path=kb)
        result = s.parsed_collections
        assert result == {"docs": kb}

    def test_kb_path_expands_user_home(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        kb = home / "docs"
        kb.mkdir(parents=True)
        monkeypatch.setenv("HOME", str(home))

        s = Settings(kb_path="~/docs")

        assert s.parsed_collections == {"docs": kb}

    def test_raises_when_neither_set(self, monkeypatch):
        monkeypatch.delenv("KB_PATH", raising=False)
        monkeypatch.delenv("KB_COLLECTIONS", raising=False)
        s = Settings()
        with pytest.raises(ValueError, match="Set KB_COLLECTIONS or KB_PATH"):
            _ = s.parsed_collections

    def test_raises_when_both_set(self, tmp_path):
        kb = tmp_path / "docs"
        kb.mkdir()
        s = Settings(kb_path=kb, kb_collections=f"docs:{kb}")
        with pytest.raises(
            ValueError, match="KB_COLLECTIONS.*KB_PATH|KB_PATH.*KB_COLLECTIONS"
        ):
            _ = s.parsed_collections

    def test_only_kb_collections_works(self, tmp_path, monkeypatch):
        monkeypatch.delenv("KB_PATH", raising=False)
        kb = tmp_path / "docs"
        kb.mkdir()
        s = Settings(kb_collections=f"docs:{kb}")
        result = s.parsed_collections
        assert result == {"docs": kb}

    def test_kb_collections_expands_user_home(self, tmp_path, monkeypatch):
        monkeypatch.delenv("KB_PATH", raising=False)
        home = tmp_path / "home"
        kb = home / "docs"
        kb.mkdir(parents=True)
        monkeypatch.setenv("HOME", str(home))

        s = Settings(kb_collections="docs:~/docs")

        assert s.parsed_collections == {"docs": kb}

    def test_only_kb_path_works(self, tmp_path):
        kb = tmp_path / "docs"
        kb.mkdir()
        s = Settings(kb_path=kb)
        result = s.parsed_collections
        assert result == {"docs": kb}

    def test_invalid_format_raises(self, monkeypatch):
        monkeypatch.delenv("KB_PATH", raising=False)
        s = Settings(kb_collections="no-colon-here")
        with pytest.raises(ValueError, match="Invalid KB_COLLECTIONS entry"):
            _ = s.parsed_collections

    def test_nonexistent_path_raises(self, tmp_path, monkeypatch):
        monkeypatch.delenv("KB_PATH", raising=False)
        s = Settings(kb_collections=f"docs:{tmp_path / 'nope'}")
        with pytest.raises(ValueError, match="does not exist"):
            _ = s.parsed_collections

    def test_file_path_raises(self, tmp_path, monkeypatch):
        monkeypatch.delenv("KB_PATH", raising=False)
        f = tmp_path / "file.txt"
        f.write_text("hi")
        s = Settings(kb_collections=f"docs:{f}")
        with pytest.raises(ValueError, match="not a directory"):
            _ = s.parsed_collections

    @pytest.mark.parametrize("name", ["docs", "team_docs", "team-docs", "docs2"])
    def test_valid_collection_name_slugs(self, tmp_path, monkeypatch, name):
        monkeypatch.delenv("KB_PATH", raising=False)
        kb = tmp_path / "kb"
        kb.mkdir()
        s = Settings(kb_collections=f"{name}:{kb}")

        assert s.parsed_collections == {name: kb}

    @pytest.mark.parametrize(
        "name",
        ["../escape", "foo/bar", "", "   ", "team docs"],
    )
    def test_invalid_collection_names_raise(self, tmp_path, monkeypatch, name):
        monkeypatch.delenv("KB_PATH", raising=False)
        kb = tmp_path / "kb"
        kb.mkdir()
        s = Settings(kb_collections=f"{name}:{kb}")

        with pytest.raises(ValueError, match="Invalid collection name"):
            _ = s.parsed_collections

    def test_duplicate_collection_names_raise(self, tmp_path, monkeypatch):
        monkeypatch.delenv("KB_PATH", raising=False)
        kb = tmp_path / "kb"
        kb.mkdir()
        s = Settings(kb_collections=f"docs:{kb},docs:{kb}")

        with pytest.raises(ValueError, match="Duplicate collection name"):
            _ = s.parsed_collections


class TestCollectionRegistry:
    def test_collection_names_sorted(self, tmp_path):
        from trace_search.collections.collection_registry import CollectionRegistry

        kb1 = tmp_path / "beta"
        kb2 = tmp_path / "alpha"
        kb1.mkdir()
        kb2.mkdir()

        reg = CollectionRegistry({"beta": kb1, "alpha": kb2})
        assert reg.collection_names == ["alpha", "beta"]

    def test_default_index_root_stays_inside_collection_kb(self, tmp_path):
        from trace_search.collections.collection_registry import CollectionRegistry

        kb = tmp_path / "docs"
        kb.mkdir()

        reg = CollectionRegistry({"docs": kb})
        assert reg.collections["docs"].index_path == kb / ".mcp-search" / "indexes"

    def test_explicit_index_root_uses_collection_subdir(self, tmp_path):
        from trace_search.collections.collection_registry import CollectionRegistry

        kb = tmp_path / "docs"
        index_root = tmp_path / "indexes"
        kb.mkdir()

        reg = CollectionRegistry({"docs": kb}, index_root=index_root)
        assert reg.collections["docs"].index_path == index_root / "docs"

    def test_resolve_specific(self, tmp_path):
        from trace_search.collections.collection_registry import CollectionRegistry

        kb = tmp_path / "docs"
        kb.mkdir()

        reg = CollectionRegistry({"docs": kb})
        cols = reg._resolve("docs")
        assert len(cols) == 1
        assert cols[0].name == "docs"

    def test_resolve_unknown_raises(self, tmp_path):
        from trace_search.collections.collection_registry import CollectionRegistry

        kb = tmp_path / "docs"
        kb.mkdir()

        reg = CollectionRegistry({"docs": kb})
        with pytest.raises(ValueError, match="Unknown collection 'nope'"):
            reg._resolve("nope")

    def test_resolve_all(self, tmp_path):
        from trace_search.collections.collection_registry import CollectionRegistry

        kb1 = tmp_path / "a"
        kb2 = tmp_path / "b"
        kb1.mkdir()
        kb2.mkdir()

        reg = CollectionRegistry({"a": kb1, "b": kb2})
        assert len(reg._resolve(None)) == 2
        assert len(reg._resolve("all")) == 2


class TestCollectionReset:
    def test_reset_clears_all_slots(self, tmp_path):
        from unittest.mock import MagicMock

        from trace_search.collections.collection_registry import Collection

        col = Collection(name="x", kb_path=tmp_path, index_path=tmp_path)
        col._indexer = MagicMock()
        col._semantic = MagicMock()
        col._keyword = MagicMock()
        col._hybrid = MagicMock()

        col.reset()

        assert col._indexer is None
        assert col._semantic is None
        assert col._keyword is None
        assert col._hybrid is None


class TestListDocumentsLimit:
    def test_limit_respected_single_folder(self, tmp_path):
        from trace_search.collections.collection_registry import CollectionRegistry

        kb = tmp_path / "docs"
        kb.mkdir()
        folder = kb / "section"
        folder.mkdir()
        for i in range(25):
            (folder / f"doc_{i:02d}.md").write_text(f"# Doc {i}\n\nContent.")

        reg = CollectionRegistry({"docs": kb})
        result = reg.list_documents(folder=None, limit=10, collection=None)
        listed = [line for line in result.splitlines() if line.startswith("- **")]
        assert len(listed) == 10

    def test_limit_larger_than_folder_returns_all(self, tmp_path):
        from trace_search.collections.collection_registry import CollectionRegistry

        kb = tmp_path / "docs"
        kb.mkdir()
        folder = kb / "section"
        folder.mkdir()
        for i in range(5):
            (folder / f"doc_{i}.md").write_text(f"# Doc {i}\n\nContent.")

        reg = CollectionRegistry({"docs": kb})
        result = reg.list_documents(folder=None, limit=50, collection=None)
        listed = [line for line in result.splitlines() if line.startswith("- **")]
        assert len(listed) == 5

    @pytest.mark.parametrize("limit", [0, -10])
    def test_invalid_limit_defaults_to_50(self, tmp_path, limit):
        from trace_search.collections.collection_registry import CollectionRegistry

        kb = tmp_path / "docs"
        kb.mkdir()
        for i in range(60):
            (kb / f"doc_{i:02d}.md").write_text(f"# Doc {i}\n\nContent.")

        reg = CollectionRegistry({"docs": kb})
        result = reg.list_documents(folder=None, limit=limit, collection=None)
        listed = [line for line in result.splitlines() if line.startswith("- **")]
        assert len(listed) == 50

    def test_large_limit_caps_at_500(self, tmp_path):
        from trace_search.collections.collection_registry import CollectionRegistry

        kb = tmp_path / "docs"
        kb.mkdir()
        for i in range(520):
            (kb / f"doc_{i:03d}.md").write_text(f"# Doc {i}\n\nContent.")

        reg = CollectionRegistry({"docs": kb})
        result = reg.list_documents(folder=None, limit=10_000, collection=None)
        listed = [line for line in result.splitlines() if line.startswith("- **")]
        assert len(listed) == 500


class TestGetDocumentWarning:
    def test_traversal_rejection_emits_warning(self, tmp_path, caplog):
        import logging

        from trace_search.collections.collection_registry import CollectionRegistry

        kb = tmp_path / "docs"
        kb.mkdir()

        reg = CollectionRegistry({"docs": kb})
        with caplog.at_level(
            logging.WARNING, logger="trace_search.collections.collection_registry"
        ):
            result = reg.get_document("../../etc/passwd", "docs")

        assert "rejected traversal" in caplog.text
        assert "Document not found" in result

    def test_extraction_failure_emits_warning(self, tmp_path, caplog):
        import logging
        from unittest.mock import patch

        from trace_search.collections.collection_registry import CollectionRegistry

        kb = tmp_path / "docs"
        kb.mkdir()
        doc = kb / "broken.md"
        doc.write_text("# Broken")

        reg = CollectionRegistry({"docs": kb})
        with caplog.at_level(
            logging.WARNING, logger="trace_search.collections.collection_registry"
        ):
            with patch(
                "trace_search.collections.collection_registry.extract_content",
                side_effect=RuntimeError("disk read failed"),
            ):
                result = reg.get_document("broken.md", "docs")

        assert "extraction failed" in caplog.text
        assert "broken.md" in caplog.text
        assert "disk read failed" in caplog.text
        assert result == "Error reading document: broken.md"
        assert "disk read failed" not in result


class TestBuildMultiMcp:
    def test_tools_have_collection_param(self, tmp_path):
        from trace_search.server.mcp_tools import build_multi_mcp

        kb = tmp_path / "docs"
        kb.mkdir()

        mcp, tools = build_multi_mcp("test-trace", {"docs": kb})
        assert mcp.name == "test-trace"
        assert set(tools.keys()) == {
            "search",
            "semantic_search",
            "keyword_search",
            "search_hybrid",
            "get_document",
            "list_documents",
            "index_stats",
            "reindex",
            "doctor",
        }


class TestMultiCollectionFilters:
    """End-to-end filter behavior across multiple knowledge bases."""

    def _make_registry(self, tmp_path):
        from tests.test_runtime_hardening import FakeBackend
        from trace_search.collections.collection_registry import CollectionRegistry

        docs = tmp_path / "docs"
        brain = tmp_path / "brain"
        docs.mkdir()
        brain.mkdir()
        (docs / "architecture").mkdir()
        (docs / "rfcs").mkdir()
        (brain / "architecture").mkdir()
        (docs / "architecture" / "intro.md").write_text(
            "# docs arch\n\nrouter design", encoding="utf-8"
        )
        (docs / "rfcs" / "001.md").write_text(
            "# RFC 001\n\nrouter behavior", encoding="utf-8"
        )
        (brain / "architecture" / "notes.md").write_text(
            "# brain arch\n\nrouter scaling", encoding="utf-8"
        )

        registry = CollectionRegistry({"docs": docs, "brain": brain})
        registry._backend = FakeBackend()
        registry._warmed = True
        for col in registry.collections.values():
            col.ensure_index(registry.backend)
        return registry

    def test_adaptive_search_path_prefix_scopes_each_collection(self, tmp_path):
        from trace_search.retrieval.search import parse_filters

        registry = self._make_registry(tmp_path)
        result = registry.search_adaptive(
            "router",
            top_k=5,
            collection=None,
            filters=parse_filters(path_prefix="architecture/"),
        )
        assert result.hits
        for hit in result.hits:
            assert hit["path"].startswith("architecture/")
            assert hit.get("collection") in {"docs", "brain"}
        assert {hit.get("collection") for hit in result.hits} == {"docs", "brain"}
        assert result.route.filters.path_prefix == ("architecture/",)

    def test_keyword_search_filters_respect_explicit_collection(self, tmp_path):
        from trace_search.retrieval.search import parse_filters

        registry = self._make_registry(tmp_path)
        results = registry.search_keyword(
            "router",
            top_k=5,
            collection="brain",
            filters=parse_filters(path_prefix="architecture/"),
        )
        assert results
        for hit in results:
            assert hit["path"].startswith("architecture/")

    def test_list_documents_path_prefix_scopes_each_collection(self, tmp_path):
        from trace_search.retrieval.search import parse_filters

        registry = self._make_registry(tmp_path)
        rendered = registry.list_documents(
            folder=None,
            limit=50,
            collection=None,
            filters=parse_filters(path_prefix="rfcs/"),
        )
        assert "rfcs/001.md" in rendered
        assert "intro.md" not in rendered
        assert "notes.md" not in rendered

    def test_instructions_list_collections(self, tmp_path):
        from trace_search.server.mcp_tools import _build_multi_instructions

        result = _build_multi_instructions(["ai-context", "docs"])
        assert '"ai-context"' in result
        assert '"docs"' in result
        assert "collection" in result


class TestMergeResults:
    def test_merge_interleaves_by_rank(self):
        from trace_search.collections.collection_registry import CollectionRegistry

        results_a = [
            {"path": "a.md", "score": 5.0, "source": "keyword"},
            {"path": "b.md", "score": 3.0, "source": "keyword"},
        ]
        results_b = [
            {"path": "c.md", "score": 4.0, "source": "keyword"},
            {"path": "d.md", "score": 1.0, "source": "keyword"},
        ]
        merged = CollectionRegistry._merge_results(
            [results_a, results_b],
            top_k=3,
            collection_names=["a", "b"],
        )
        assert len(merged) == 3
        assert merged[0]["path"] == "a.md"
        assert merged[0]["collection"] == "a"
        assert merged[1]["path"] == "c.md"
        assert merged[1]["collection"] == "b"
        assert merged[2]["path"] == "b.md"

    def test_merge_does_not_starve_small_collection(self):
        """Regression: raw BM25 scores from a large corpus (higher IDF) used to
        crowd out a small collection's genuinely relevant top hit."""
        from trace_search.collections.collection_registry import CollectionRegistry

        large = [
            {"path": f"large_{i}.md", "score": 12.0 - i * 0.5, "source": "keyword"}
            for i in range(5)
        ]
        small = [
            {"path": "answer.md", "score": 3.2, "source": "keyword"},
            {"path": "other.md", "score": 1.1, "source": "keyword"},
        ]

        # The old merge sorted raw scores: the small collection never surfaced.
        by_raw_score = sorted(large + small, key=lambda h: h["score"], reverse=True)
        assert all(h["path"].startswith("large_") for h in by_raw_score[:5])

        merged = CollectionRegistry._merge_results(
            [large, small],
            top_k=5,
            collection_names=["large", "small"],
        )
        assert merged[0]["path"] == "large_0.md"
        assert merged[1]["path"] == "answer.md"
        assert merged[1]["collection"] == "small"

    def test_merge_handles_mixed_score_types_across_collections(self):
        """Adaptive search can return raw BM25 for one collection and hybrid
        RRF (~0.03 scale) for another; rank fusion must not compare them."""
        from trace_search.collections.collection_registry import CollectionRegistry

        keyword_hits = [
            {"path": "k1.md", "score": 8.5, "source": "keyword"},
            {"path": "k2.md", "score": 7.0, "source": "keyword"},
        ]
        hybrid_hits = [
            {"path": "h1.md", "score": 0.9, "rrf_score": 0.032, "source": "hybrid"},
            {"path": "h2.md", "score": 0.8, "rrf_score": 0.030, "source": "hybrid"},
        ]
        merged = CollectionRegistry._merge_results(
            [keyword_hits, hybrid_hits],
            top_k=2,
            collection_names=["kw", "hy"],
        )
        assert [h["path"] for h in merged] == ["k1.md", "h1.md"]

    def test_format_search_context_preserves_fused_order(self):
        """Regression: format_search_context used to re-sort merged hits by
        raw score, demoting the hybrid collection's rank-1 hit below the
        keyword collection's rank-2 hit in the rendered output."""
        from trace_search.collections.collection_registry import CollectionRegistry
        from trace_search.retrieval.formatting import format_search_context

        keyword_hits = [
            {
                "path": "k1.md",
                "title": "K1",
                "folder": "",
                "score": 8.5,
                "source": "keyword",
                "content": "alpha topic overview",
            },
            {
                "path": "k2.md",
                "title": "K2",
                "folder": "",
                "score": 7.0,
                "source": "keyword",
                "content": "alpha topic details",
            },
        ]
        hybrid_hits = [
            {
                "path": "h1.md",
                "title": "H1",
                "folder": "",
                "score": 0.9,
                "rrf_score": 0.032,
                "source": "hybrid",
                "content": "alpha topic notes",
            },
        ]
        merged = CollectionRegistry._merge_results(
            [keyword_hits, hybrid_hits],
            top_k=3,
            collection_names=["kw", "hy"],
        )
        rendered = format_search_context(merged, query="alpha")
        assert (
            rendered.index("### 1. K1")
            < rendered.index("### 2. H1")
            < rendered.index("### 3. K2")
        )


class TestCrossCollectionFairness:
    """End-to-end: a small collection's relevant doc must survive merging
    with a much larger collection whose BM25 statistics inflate raw scores."""

    QUERY = "kubernetes deployment"

    def _make_registry(self, tmp_path):
        from tests.test_runtime_hardening import FakeBackend
        from trace_search.collections.collection_registry import CollectionRegistry

        large = tmp_path / "large"
        small = tmp_path / "small"
        large.mkdir()
        small.mkdir()

        # Large collection: 40 docs; a few mention the query terms in passing,
        # so the terms are rare in a big corpus (high IDF -> big raw scores).
        for i in range(34):
            (large / f"note_{i:02d}.md").write_text(
                f"# Note {i}\n\nMeeting summary about billing, invoices and "
                f"quarterly planning item {i}.",
                encoding="utf-8",
            )
        for i in range(6):
            (large / f"kubernetes-incident-{i}.md").write_text(
                f"# Kubernetes incident {i}\n\nRotated credentials on the "
                "cluster. The kubernetes deployment for service "
                f"s{i} was restarted during maintenance. Kubernetes deployment "
                "events were archived afterwards.",
                encoding="utf-8",
            )

        # Small collection: 3 docs; one is the genuinely relevant answer.
        (small / "kubernetes-deployment-guide.md").write_text(
            "# Kubernetes deployment guide\n\nHow we run a kubernetes "
            "deployment: build the image, apply the manifest, verify the "
            "rollout status.",
            encoding="utf-8",
        )
        (small / "onboarding.md").write_text(
            "# Onboarding\n\nAccounts, laptop setup and first week schedule.",
            encoding="utf-8",
        )
        (small / "style.md").write_text(
            "# Style guide\n\nWriting conventions for internal docs.",
            encoding="utf-8",
        )

        registry = CollectionRegistry({"large": large, "small": small})
        registry._backend = FakeBackend()
        registry._warmed = True
        for col in registry.collections.values():
            col.ensure_index(registry.backend)
        return registry

    def test_small_collection_hit_survives_merge(self, tmp_path):
        from trace_search.retrieval.search import SearchFilters

        registry = self._make_registry(tmp_path)
        filters = SearchFilters()

        large_hits = registry.collections["large"].search(
            "keyword", self.QUERY, 5, filters, registry.backend
        )
        small_hits = registry.collections["small"].search(
            "keyword", self.QUERY, 5, filters, registry.backend
        )
        assert small_hits and small_hits[0]["path"] == "kubernetes-deployment-guide.md"

        # Precondition for the regression: the large corpus's raw scores beat
        # the small collection's best hit, so the old raw-score merge starved
        # it out of the top ranks. If this stops holding, the fixture no
        # longer exercises the bug.
        small_best = float(small_hits[0]["score"])
        outscoring = [h for h in large_hits if float(h["score"]) > small_best]
        assert len(outscoring) >= 2

        merged = registry.search_keyword(
            self.QUERY, top_k=5, collection=None, filters=filters
        )
        top2 = [(h["collection"], h["path"]) for h in merged[:2]]
        assert ("small", "kubernetes-deployment-guide.md") in top2
        assert {h["collection"] for h in merged} == {"large", "small"}

    def test_rendered_adaptive_search_keeps_small_collection_on_top(self, tmp_path):
        """The production `search` tool path: search_adaptive rendered through
        format_search_context must present the small collection's relevant doc
        among the top two documents, not re-sorted down by raw score."""
        from trace_search.retrieval.formatting import format_search_context

        registry = self._make_registry(tmp_path)
        result = registry.search_adaptive(self.QUERY, top_k=5, collection=None)
        rendered = format_search_context(
            result.hits, query=self.QUERY, route=result.route, max_documents=5
        )
        assert "### 3." in rendered
        assert rendered.index("kubernetes-deployment-guide.md") < rendered.index(
            "### 3."
        )

    def test_merge_respects_top_k(self):
        from trace_search.collections.collection_registry import CollectionRegistry

        results = [
            {"path": f"{i}.md", "score": float(i), "source": "keyword"}
            for i in range(10)
        ]
        merged = CollectionRegistry._merge_results(
            [results], top_k=3, collection_names=["x"]
        )
        assert len(merged) == 3


class TestResolveAllCaseInsensitive:
    def _make_registry(self, tmp_path):
        from trace_search.collections.collection_registry import CollectionRegistry

        docs = tmp_path / "docs"
        brain = tmp_path / "brain"
        docs.mkdir()
        brain.mkdir()
        return CollectionRegistry({"docs": docs, "brain": brain})

    def test_resolve_all_lowercase(self, tmp_path):
        reg = self._make_registry(tmp_path)
        result = reg._resolve("all")
        assert len(result) == 2

    def test_resolve_all_uppercase(self, tmp_path):
        reg = self._make_registry(tmp_path)
        result = reg._resolve("ALL")
        assert len(result) == 2

    def test_resolve_all_mixed_case(self, tmp_path):
        reg = self._make_registry(tmp_path)
        result = reg._resolve("All")
        assert len(result) == 2

    def test_resolve_none_returns_all(self, tmp_path):
        reg = self._make_registry(tmp_path)
        result = reg._resolve(None)
        assert len(result) == 2

    def test_resolve_unknown_raises(self, tmp_path):
        reg = self._make_registry(tmp_path)
        with pytest.raises(ValueError, match="docs"):
            reg._resolve("Docs")

    def test_resolve_known_collection_case_sensitive(self, tmp_path):
        reg = self._make_registry(tmp_path)
        result = reg._resolve("docs")
        assert len(result) == 1
        assert result[0].name == "docs"


class TestTraceServerImport:
    def test_import_succeeds(self):
        import trace_search.server.trace_server as ks

        assert hasattr(ks, "main")
        assert callable(ks.main)
