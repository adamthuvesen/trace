"""Behavioral guarantees at runtime and persistence boundaries."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from tests.search_hits import make_hit
from tests.test_runtime_hardening import FakeBackend
from tests.typed_fakes import fake_indexer, settings_without_dotenv
from trace_search.collections.collection_registry import CollectionRegistry
from trace_search.collections.errors import DocumentNotFoundError, ReindexError
from trace_search.collections.operations import TraceOperations
from trace_search.config import parse_kb_collections
from trace_search.indexing.index_metadata import (
    INDEX_METADATA_VERSION,
    build_index_metadata,
    index_metadata_from_dict,
    metadata_matches_settings,
    metadata_query_compatible,
)
from trace_search.indexing.index_store import (
    IndexBusyError,
    IndexCorruptError,
    load_snapshot,
    read_current,
    write_snapshot,
    writer_lock,
)
from trace_search.indexing.wiki_indexer import WikiIndexer
from trace_search.retrieval.formatting import format_search_context
from trace_search.retrieval.search import AdaptiveSearch, KeywordSearch, SemanticSearch
from trace_search.retrieval.search_types import SearchResponse, parse_filters


@pytest.fixture
def indexed(tmp_path: Path):
    kb = tmp_path / "docs"
    kb.mkdir()
    (kb / "intro.md").write_text("# Intro\n\nOriginal introduction.")
    indexer = WikiIndexer(kb, tmp_path / "index", FakeBackend())
    indexer.build_index()
    return indexer


@pytest.mark.parametrize("name", ["all", "ALL"])
def test_all_is_a_reserved_collection_name(tmp_path, name):
    with pytest.raises(ValueError, match=r"reserved.*Choose another collection name"):
        parse_kb_collections(f"{name}:{tmp_path}")


def test_empty_collection_path_cannot_select_current_directory():
    with pytest.raises(ValueError, match="must not be empty"):
        parse_kb_collections("docs:  ")


@pytest.mark.parametrize(
    "filename,body",
    [("broken.md", b"\xff"), ("broken.ipynb", b"not-json"), ("broken.py", b"\xff")],
)
def test_failed_extraction_preserves_generation_and_retry_reextracts(indexed, filename, body):
    generation = read_current(indexed.index_root)
    source = indexed.kb_path / filename
    source.write_bytes(body)
    with pytest.raises(RuntimeError, match="Failed to extract"):
        indexed.build_index()
    assert read_current(indexed.index_root) == generation
    source.write_text(
        "# Repaired\n\nrepaired document" if source.suffix == ".md" else '{"cells": []}'
    )
    indexed.build_index()
    assert read_current(indexed.index_root) != generation
    assert any(record.path == filename for record in indexed.snapshot().metadata.source_files)


def test_source_mutation_during_extraction_aborts_publication(indexed):
    from trace_search.indexing import index_builder

    original = index_builder.extract_content
    source = indexed.kb_path / "intro.md"
    source.write_text("# Intro\n\nVersion before extraction.")
    generation = read_current(indexed.index_root)

    def mutate(captured):
        text = original(captured)
        source.write_text("# Intro\n\nChanged during extraction.")
        return text

    with (
        patch.object(index_builder, "extract_content", side_effect=mutate),
        pytest.raises(RuntimeError, match="Source changed during extraction"),
    ):
        indexed.build_index()
    assert read_current(indexed.index_root) == generation


def test_touch_refreshes_since_filter_without_reembedding(indexed):
    before = indexed.snapshot()
    source = indexed.kb_path / "intro.md"
    future = source.stat().st_mtime + 10
    os.utime(source, (future, future))
    with patch.object(indexed.backend, "encode", side_effect=AssertionError("must reuse vectors")):
        indexed.build_index()
    after = indexed.snapshot()
    assert after.generation != before.generation
    assert after.chunks[0]["source_mtime"] == future
    assert np.array_equal(after.embeddings, before.embeddings)
    assert after.metadata.source_files[0].mtime == future
    assert KeywordSearch(indexed).search("Intro", filters=parse_filters(since="2100-01-01")) == []


def test_snapshot_payloads_are_read_only(indexed):
    snapshot = indexed.snapshot()
    with pytest.raises(TypeError):
        snapshot.chunks[0]["path"] = "wrong.md"
    with pytest.raises(TypeError):
        snapshot.row_by_id["wrong.md::0"] = 0
    with pytest.raises(ValueError):
        snapshot.embeddings[0, 0] = 99
    with pytest.raises(ValueError):
        snapshot.embeddings.setflags(write=True)
    assert isinstance(snapshot.texts, tuple)
    assert isinstance(snapshot.metadata.source_files, tuple)
    hit = KeywordSearch(indexed).search("Intro")[0]
    with pytest.raises(TypeError):
        hit.metadata["path"] = "wrong.md"
    assert hit.ref.document.path == hit.path == "intro.md"


def test_recipe_records_injected_backend_and_bm25_change_forces_rebuild(indexed):
    before = indexed.snapshot().metadata
    assert before.embedding_model == "fake"
    assert before.embedding_dims == 3
    assert before.embedding_backend.endswith("FakeBackend")
    config = indexed.config.model_copy(update={"bm25_k1": 2.0, "bm25_b": 0.8})
    fresh = WikiIndexer(indexed.kb_path, indexed.index_root, FakeBackend(), config=config)
    with patch.object(fresh.backend, "encode", wraps=fresh.backend.encode) as encode:
        fresh.build_index()
    encode.assert_called_once()
    after = fresh.snapshot().metadata
    assert after is not None
    assert after.build_recipe["bm25_k1"] == 2.0
    assert after.build_recipe["bm25_b"] == 0.8
    assert after.recipe_fingerprint != before.recipe_fingerprint
    bm25 = fresh.snapshot().bm25
    assert bm25 is not None
    assert bm25.k1 == 2.0
    assert bm25.b == 0.8


def test_v6_is_readable_and_query_compatible_but_requires_full_rebuild(tmp_path):
    config = settings_without_dotenv()
    raw = build_index_metadata(
        kb_path=tmp_path,
        build_started_at="",
        build_completed_at="",
        document_count=0,
        chunk_count=0,
        config=config,
    ).to_dict()
    raw["version"] = 6
    for key in (
        "embedding_backend",
        "bm25_k1",
        "bm25_b",
        "tokenizer_version",
        "transformation_version",
    ):
        raw.pop(key)
    decoded = index_metadata_from_dict(raw)
    assert decoded is not None and decoded.version == 6
    assert metadata_query_compatible(decoded, config)
    assert not metadata_matches_settings(decoded, config)


@pytest.mark.parametrize(
    "change",
    [
        lambda raw: raw.update(embedding_dims="3"),
        lambda raw: raw.update(unrecognized=True),
        lambda raw: raw["source_files"].append("bad"),
    ],
)
def test_malformed_v7_metadata_is_corruption(indexed, change):
    path = indexed.index_root / read_current(indexed.index_root) / "index_metadata.json"
    raw = json.loads(path.read_text())
    assert raw["version"] == INDEX_METADATA_VERSION
    change(raw)
    path.write_text(json.dumps(raw))
    with pytest.raises(IndexCorruptError, match="reindex"):
        load_snapshot(indexed.index_root)


@pytest.mark.parametrize("pointer", ["../../outside", "/tmp/outside", "gen-../outside"])
def test_current_cannot_escape_the_index_root(indexed, pointer):
    (indexed.index_root / "CURRENT").write_text(pointer)
    with pytest.raises(IndexCorruptError, match="CURRENT"):
        load_snapshot(indexed.index_root)


def test_direct_publication_cannot_bypass_another_writer_lock(indexed):
    snapshot = indexed.snapshot()
    with writer_lock(indexed.index_root), ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(write_snapshot, indexed.index_root, snapshot)
        with pytest.raises(IndexBusyError):
            future.result()


def test_empty_published_generation_keeps_its_identity(tmp_path):
    kb = tmp_path / "empty"
    kb.mkdir()
    indexer = WikiIndexer(kb, tmp_path / "index", FakeBackend())
    indexer.build_index()
    loaded = WikiIndexer(kb, tmp_path / "index", FakeBackend()).snapshot()
    assert len(loaded) == 0
    assert loaded.generation == read_current(indexer.index_root)
    assert loaded.metadata is not None


def test_adaptive_preserves_candidate_depths_and_one_snapshot(indexed):
    hits = [make_hit(f"doc{i}.md", score=1.0, source="keyword") for i in range(6)]
    adaptive = AdaptiveSearch(indexed)
    with (
        patch.object(adaptive.keyword, "search", return_value=hits[:3]) as gate,
        patch.object(adaptive.hybrid.keyword, "search", return_value=hits) as lexical,
        patch.object(adaptive.hybrid.semantic, "search", return_value=[]) as semantic,
        patch.object(indexed, "snapshot", wraps=indexed.snapshot) as snapshot,
    ):
        adaptive.search("a natural language question", top_k=3)
    snapshot.assert_called_once()
    assert gate.call_args.kwargs["max_results"] == 3
    assert lexical.call_args.kwargs["max_results"] == 6
    assert semantic.call_args.kwargs["top_k"] == 12
    assert (
        gate.call_args.kwargs["snapshot"]
        is lexical.call_args.kwargs["snapshot"]
        is semantic.call_args.kwargs["snapshot"]
    )


def test_reindex_during_adaptive_query_keeps_neighbors_in_original_generation(tmp_path):
    kb = tmp_path / "docs"
    kb.mkdir()
    for name in ("a", "b"):
        (kb / f"{name}.md").write_text(
            f"# Query {name}\n\nold {name}\n\n## Details\n\nold neighbor {name}"
        )
    registry = CollectionRegistry({"docs": kb})
    registry._backend = FakeBackend()
    registry._warmed = True
    indexer = registry.collections["docs"].indexer(registry.shared_backend)
    original = KeywordSearch.search
    first_generation = indexer.snapshot().generation
    published = False

    def publish(search, *args, **kwargs):
        nonlocal published
        hits = original(search, *args, **kwargs)
        if not published:
            published = True
            for name in ("a", "b"):
                (kb / f"{name}.md").write_text(
                    f"# Query {name}\n\nnew {name}\n\n## Details\n\nnew neighbor {name}"
                )
            indexer.build_index(force=True)
        return hits

    with (
        patch.object(KeywordSearch, "search", publish),
        patch.object(indexer, "snapshot", wraps=indexer.snapshot) as snapshot,
    ):
        response = TraceOperations(registry).search_response("adaptive", "query", 2)
    snapshot.assert_called_once()
    assert read_current(indexer.index_root) != first_generation
    assert all(hit.ref.generation == first_generation for hit in response.hits)
    assert all(
        "new" not in hit.content and "new" not in (hit.neighbor_content or "")
        for hit in response.hits
    )


def test_formatter_preserves_explicit_response_order():
    first = make_hit("first.md", title="First", score=0.1, content="first")
    second = make_hit("second.md", title="Second", score=99.0, content="second")
    output = format_search_context(SearchResponse((first, second)), query="")
    assert output.index("### 1. First") < output.index("### 2. Second")


def test_same_path_followups_identify_each_selected_collection(tmp_path):
    paths = {name: tmp_path / name for name in ("one", "two")}
    for kb in paths.values():
        kb.mkdir()
        (kb / "shared.md").write_text("# Shared\n\nshared reference")
    registry = CollectionRegistry(paths)
    registry._backend = FakeBackend()
    registry._warmed = True
    output = TraceOperations(registry).search("shared", top_k=2)
    assert 'get_document(path="shared.md", collection="one")' in output
    assert 'get_document(path="shared.md", collection="two")' in output


def test_partial_reindex_reports_completed_and_failed_collections(tmp_path):
    good = tmp_path / "good"
    bad = tmp_path / "bad"
    good.mkdir()
    bad.mkdir()
    (good / "doc.md").write_text("# Good\n\ngood document")
    (bad / "broken.ipynb").write_text("not json")
    registry = CollectionRegistry({"good": good, "bad": bad})
    registry._backend = FakeBackend()
    registry._warmed = True
    with pytest.raises(ReindexError) as failure:
        TraceOperations(registry).reindex()
    assert failure.value.completed == (("good", 1),)
    assert failure.value.failed[0][0] == "bad"
    assert registry.collections["good"].indexer(registry.shared_backend).has_index()
    assert "Reindex complete" not in str(failure.value)


@dataclass
class _UnhashableBackend:
    vector: tuple[float, ...]
    model_name: str = "same-model"
    dim: int = 2

    def encode_one(self, query):
        return np.asarray(self.vector, dtype=np.float32)


def test_query_cache_isolates_same_name_unhashable_backends():
    one = SemanticSearch(fake_indexer(backend=_UnhashableBackend((1.0, 0.0))))
    two = SemanticSearch(fake_indexer(backend=_UnhashableBackend((0.0, 1.0))))
    assert one._get_query_embedding("same query").tolist() == [1.0, 0.0]
    assert two._get_query_embedding("same query").tolist() == [0.0, 1.0]


def test_document_fetch_is_live_and_missing_is_an_error(indexed):
    registry = CollectionRegistry({"docs": indexed.kb_path})
    (indexed.kb_path / "intro.md").write_text("# Intro\n\nLive new content")
    assert "Live new content" in TraceOperations(registry).get_document("intro.md")
    with pytest.raises(DocumentNotFoundError):
        TraceOperations(registry).get_document("missing.md")


@pytest.mark.parametrize("name", ["My Documents", "my.wiki"])
def test_implicit_collection_keeps_valid_filesystem_names(tmp_path, name):
    kb = tmp_path / name
    kb.mkdir()
    (kb / "intro.md").write_text("# Intro")
    config = settings_without_dotenv(kb_path=kb, kb_collections=None)
    assert config.parsed_collections == {name: kb}
    registry = CollectionRegistry(config.parsed_collections, config=config)
    assert registry.collection_names == [name]
    assert "intro.md" in TraceOperations(registry).list_documents(collection=name)


def test_implicit_all_directory_has_an_unambiguous_default_selector(tmp_path):
    kb = tmp_path / "all"
    kb.mkdir()
    config = settings_without_dotenv(kb_path=kb, kb_collections=None)
    assert config.parsed_collections == {"default": kb}
    assert (
        CollectionRegistry(config.parsed_collections, config=config).resolve("default")[0].kb_path
        == kb
    )


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("document_count", 999, "document count"),
        ("source_files", [], "source inventory"),
    ],
)
def test_v7_metadata_cannot_contradict_document_identity(indexed, field, value, message):
    path = indexed.index_root / read_current(indexed.index_root) / "index_metadata.json"
    raw = json.loads(path.read_text())
    raw[field] = value
    path.write_text(json.dumps(raw))
    with pytest.raises(IndexCorruptError, match=message):
        load_snapshot(indexed.index_root)


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("document_count", 999, "document count"),
        ("source_files", (), "source inventory"),
        ("bm25_k1", 2.0, "BM25 parameters"),
        ("bm25_b", 0.8, "BM25 parameters"),
    ],
)
def test_supported_next_schema_retains_artifact_invariants(
    indexed, monkeypatch, field, value, message
):
    from trace_search.indexing import index_metadata

    next_version = index_metadata.INDEX_METADATA_VERSION + 1
    monkeypatch.setattr(index_metadata, "INDEX_METADATA_VERSION", next_version)
    snapshot = indexed.snapshot()
    metadata = replace(snapshot.metadata, version=next_version)
    restored = index_metadata.index_metadata_from_dict(metadata.to_dict())
    assert restored is not None
    assert restored.version == next_version
    with pytest.raises(ValueError, match=message):
        replace(snapshot, metadata=replace(metadata, **{field: value}))


def test_unsupported_schema_cannot_be_published_or_loaded(indexed):
    snapshot = indexed.snapshot()
    metadata = replace(snapshot.metadata, version=INDEX_METADATA_VERSION + 1)
    with pytest.raises(ValueError, match="unsupported index metadata schema"):
        write_snapshot(indexed.index_root, replace(snapshot, metadata=metadata))
    assert read_current(indexed.index_root) == snapshot.generation
    path = indexed.index_root / snapshot.generation / "index_metadata.json"
    path.write_text(json.dumps(metadata.to_dict()))
    with pytest.raises(IndexCorruptError, match="Unknown index metadata schema"):
        load_snapshot(indexed.index_root)
