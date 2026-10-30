"""Reproduce filesystem and backend failures at runtime trust boundaries."""

from __future__ import annotations

import errno
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_runtime_hardening import FakeBackend
from trace_search.collections.collection_registry import CollectionRegistry
from trace_search.collections.errors import DocumentNotFoundError
from trace_search.collections.operations import TraceOperations
from trace_search.config import Settings
from trace_search.extraction.corpus import iter_kb_files
from trace_search.indexing import index_store
from trace_search.indexing.embeddings import OnnxBackend
from trace_search.indexing.index_metadata import (
    backend_identity,
    metadata_query_compatible,
)
from trace_search.indexing.index_store import (
    IndexCorruptError,
    read_current,
    write_snapshot,
)
from trace_search.indexing.wiki_indexer import WikiIndexer
from trace_search.retrieval.search import SemanticSearch


@pytest.fixture
def indexed(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "visible.md").write_text("# Visible\n\nVisible document.")
    indexer = WikiIndexer(kb, tmp_path / "index", FakeBackend())
    indexer.build_index()
    return indexer


def test_unreadable_visible_subtree_aborts_build_and_retry_retains_documents(
    indexed, monkeypatch
):
    private = indexed.kb_path / "private"
    private.mkdir()
    (private / "important.md").write_text("# Important\n\nImportant document.")
    assert indexed.build_index() == 2
    generation = read_current(indexed.index_root)
    private.chmod(0)
    original = os.scandir
    if os.geteuid() == 0:
        # Root bypasses mode bits, so inject the OS permission result there.
        def denied(path):
            if Path(path) == private:
                raise PermissionError(errno.EACCES, "Permission denied", str(private))
            return original(path)

        monkeypatch.setattr(os, "scandir", denied)
    try:
        with pytest.raises(PermissionError, match="private"):
            indexed.build_index()
        assert read_current(indexed.index_root) == generation
    finally:
        private.chmod(0o700)
        monkeypatch.setattr(os, "scandir", original)
    (private / "important.md").write_text("# Important\n\nRestored document.")
    assert indexed.build_index() == 2
    assert read_current(indexed.index_root) != generation
    assert {chunk["path"] for chunk in indexed.snapshot().chunks} == {
        "visible.md",
        "private/important.md",
    }


@pytest.mark.parametrize("name", [".hidden", "node_modules", "ignored"])
def test_excluded_subtree_is_not_opened(tmp_path, monkeypatch, name):
    kb = tmp_path / "kb"
    kb.mkdir()
    hidden = kb / name
    hidden.mkdir()
    (hidden / "secret.md").write_text("secret")
    (kb / "visible.md").write_text("visible")
    (kb / ".traceignore").write_text("ignored/\n!/unrelated/\n")
    original = os.scandir

    def scan(path):
        if Path(path) == hidden:
            raise AssertionError("Excluded directory must not be opened")
        return original(path)

    monkeypatch.setattr(os, "scandir", scan)
    assert [path.name for path in iter_kb_files(kb)] == ["visible.md"]


def test_later_descendant_negation_keeps_existing_discovery_semantics(tmp_path):
    kb = tmp_path / "kb"
    folder = kb / "drafts"
    folder.mkdir(parents=True)
    (folder / "keep.md").write_text("kept")
    (folder / "drop.md").write_text("ignored")
    (kb / ".traceignore").write_text("drafts/\n!drafts/keep.md\n")
    assert [path.name for path in iter_kb_files(kb)] == ["keep.md"]


@pytest.mark.parametrize("existing", [False, True])
def test_collection_index_aliases_rejected_before_resource_open(tmp_path, existing):
    paths = {name: tmp_path / name for name in ("a", "b")}
    for path in paths.values():
        path.mkdir()
    probe = tmp_path / "probe"
    probe.mkdir()
    aliases = (tmp_path / "PROBE").exists()
    index_root = tmp_path / "indexes"
    if existing:
        (index_root / "Docs").mkdir(parents=True)
        (index_root / "docs").mkdir(exist_ok=True)
    if aliases:
        with pytest.raises(ValueError, match="Destination collision"):
            CollectionRegistry({"Docs": paths["a"], "docs": paths["b"]}, index_root)
        assert not list(index_root.rglob("CURRENT")) if index_root.exists() else True
    else:
        registry = CollectionRegistry(
            {"Docs": paths["a"], "docs": paths["b"]}, index_root
        )
        assert all(
            collection._indexer is None for collection in registry.collections.values()
        )
    assert not list(tmp_path.rglob(".trace-plan-*"))


def test_default_index_aliases_are_rejected(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(kb, target_is_directory=True)
    with pytest.raises(ValueError, match="Destination collision"):
        CollectionRegistry({"one": kb, "two": alias})
    assert not (kb / ".mcp-search").exists()


@pytest.mark.parametrize("relative", [".", ".."])
def test_relative_kb_path_derives_resolved_collection_name(
    tmp_path, monkeypatch, relative
):
    child = tmp_path / "child"
    child.mkdir()
    monkeypatch.chdir(child)
    config = Settings(_env_file=None, kb_path=relative, kb_collections=None)
    expected = Path(relative).resolve().name
    assert list(config.parsed_collections) == [expected]
    assert CollectionRegistry(
        config.parsed_collections, config=config
    ).collection_names == [expected]


@pytest.mark.parametrize(
    "alias", ["ignored-alias.md", "node_modules/alias.md", ".hidden/alias.md"]
)
def test_fetch_and_scan_apply_lexical_alias_exclusions(tmp_path, alias):
    kb = tmp_path / "kb"
    kb.mkdir()
    visible = kb / "visible.md"
    visible.write_text("# Visible")
    link = kb / alias
    link.parent.mkdir(exist_ok=True)
    link.symlink_to(visible)
    (kb / ".traceignore").write_text("ignored-alias.md\n")
    assert list(iter_kb_files(kb)) == [visible]
    with pytest.raises(DocumentNotFoundError):
        TraceOperations(CollectionRegistry({"docs": kb})).get_document(alias)


def test_alias_to_excluded_target_is_not_discovered_or_fetched(tmp_path):
    kb = tmp_path / "kb"
    (kb / ".hidden").mkdir(parents=True)
    target = kb / ".hidden" / "secret.md"
    target.write_text("private")
    (kb / "alias.md").symlink_to(target)
    assert list(iter_kb_files(kb)) == []
    with pytest.raises(DocumentNotFoundError):
        TraceOperations(CollectionRegistry({"docs": kb})).get_document("alias.md")


def test_plugin_class_name_cannot_claim_builtin_backend_identity(indexed):
    first_class = type("OnnxBackend", (FakeBackend,), {"__module__": "plugin_a"})
    second_class = type("OnnxBackend", (FakeBackend,), {"__module__": "plugin_b"})
    first, second = first_class(), second_class()
    assert backend_identity(first) == "plugin_a.OnnxBackend"
    assert backend_identity(second) == "plugin_b.OnnxBackend"
    assert backend_identity(OnnxBackend.__new__(OnnxBackend)) == "onnx"
    writer = WikiIndexer(indexed.kb_path, indexed.index_root, first)
    writer.build_index(force=True)
    reader = WikiIndexer(indexed.kb_path, indexed.index_root, second)
    assert not metadata_query_compatible(
        reader.snapshot().metadata, reader.config, second
    )
    with pytest.raises(ValueError, match="incompatible"):
        SemanticSearch(reader).search("Visible")


@pytest.mark.parametrize("hard_link", [False, True])
def test_writer_lock_cannot_truncate_linked_source(indexed, hard_link):
    valuable = indexed.kb_path / "valuable.md"
    valuable.write_text("protected source content")
    lock = indexed.index_root / ".write.lock"
    lock.unlink()
    if hard_link:
        os.link(valuable, lock)
    else:
        lock.symlink_to(valuable)
    generation = read_current(indexed.index_root)
    with pytest.raises(IndexCorruptError, match="lock"):
        indexed.build_index(force=True)
    assert valuable.read_text() == "protected source content"
    assert read_current(indexed.index_root) == generation


def test_stale_pointer_temp_symlink_cannot_overwrite_source(indexed):
    valuable = indexed.kb_path / "valuable.md"
    valuable.write_text("protected source content")
    (indexed.index_root / "CURRENT.tmp").symlink_to(valuable)
    indexed.build_index(force=True)
    assert valuable.read_text() == "protected source content"
    assert not (indexed.index_root / "CURRENT").is_symlink()
    assert read_current(indexed.index_root) == indexed.snapshot().generation


@pytest.mark.parametrize("exit_inherited_context", [False, True])
def test_forked_child_must_acquire_its_own_writer_lock(indexed, exit_inherited_context):
    script = r"""
import os
import sys
from pathlib import Path
from trace_search.indexing.index_store import IndexBusyError, load_snapshot, read_current, write_snapshot, writer_lock
root = Path(sys.argv[1])
snapshot = load_snapshot(root)
assert snapshot is not None
read_fd, write_fd = os.pipe()
context = writer_lock(root)
with context:
    inode = (root / '.write.lock').stat().st_ino
    child = os.fork()
    if child == 0:
        os.close(read_fd)
        try:
            if sys.argv[2] == 'True':
                context.__exit__(None, None, None)
            write_snapshot(root, snapshot)
            result = b'incorrectly published'
        except IndexBusyError:
            result = b'blocked by parent lock'
        except BaseException as error:
            result = repr(error).encode()
        os.write(write_fd, result)
        os.close(write_fd)
        os._exit(0)
    os.close(write_fd)
    _, status = os.waitpid(child, 0)
    result = os.read(read_fd, 4096)
    os.close(read_fd)
    assert os.waitstatus_to_exitcode(status) == 0
    assert result == b'blocked by parent lock', result
    assert read_current(root) == snapshot.generation
    published = write_snapshot(root, snapshot)
    assert (root / '.write.lock').stat().st_ino == inode
assert read_current(root) == published.generation
print('fork publication blocked; parent lock and publication remain valid')
"""
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(indexed.index_root),
            str(exit_inherited_context),
        ],
        capture_output=True,
        text=True,
        timeout=15,
        env={
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        },
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert "parent lock and publication remain valid" in completed.stdout


@pytest.mark.parametrize("stage", ["embedding", "pointer"])
def test_synthetic_enospc_cleans_only_failed_attempt_artifacts(
    indexed, monkeypatch, stage
):
    snapshot = indexed.snapshot()
    before = {path.name for path in indexed.index_root.glob("gen-*")}
    if stage == "embedding":

        def fail(path, *args, **kwargs):
            Path(path).write_bytes(b"synthetic partial embedding payload")
            raise OSError(errno.ENOSPC, "synthetic disk-full fault")

        monkeypatch.setattr(index_store.np, "save", fail)
    else:

        def fail(source, destination):
            raise OSError(errno.ENOSPC, "synthetic disk-full pointer fault")

        monkeypatch.setattr(index_store.os, "replace", fail)
    for _ in range(3):
        with pytest.raises(OSError, match="synthetic disk-full"):
            write_snapshot(indexed.index_root, snapshot)
        assert read_current(indexed.index_root) == snapshot.generation
        assert {path.name for path in indexed.index_root.glob("gen-*")} == before
        assert not list(indexed.index_root.glob(".CURRENT-*.tmp"))


@pytest.mark.parametrize(
    "actual,requested",
    [
        ("secret.md", "SECRET.md"),
        ("café.md", "cafe\u0301.md"),
        ("node_modules/global.md", "NODE_MODULES/global.md"),
    ],
)
def test_fetch_alias_uses_actual_filesystem_spelling_for_visibility(
    tmp_path, actual, requested
):
    kb = tmp_path / "kb"
    kb.mkdir()
    protected = kb / actual
    protected.parent.mkdir(exist_ok=True)
    protected.write_text("excluded content")
    (kb / ".traceignore").write_text(actual + "\n")
    equivalent = (kb / requested).exists()
    if not equivalent:
        public = kb / requested
        public.parent.mkdir(exist_ok=True)
        public.write_text("distinct public content")
    operations = TraceOperations(CollectionRegistry({"docs": kb}))
    if equivalent:
        with pytest.raises(DocumentNotFoundError):
            operations.get_document(requested)
    else:
        assert "distinct public content" in operations.get_document(requested)
    assert protected.read_text() == "excluded content"


def test_exact_hard_link_names_retain_distinct_visibility(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    protected = kb / "secret.md"
    protected.write_text("shared inode content")
    public = kb / "public.md"
    os.link(protected, public)
    (kb / ".traceignore").write_text("secret.md\n")
    operations = TraceOperations(CollectionRegistry({"docs": kb}))
    assert "shared inode content" in operations.get_document("public.md")
    with pytest.raises(DocumentNotFoundError):
        operations.get_document("secret.md")
    if (kb / "PUBLIC.md").exists():
        assert "shared inode content" in operations.get_document("PUBLIC.md")
    assert list(iter_kb_files(kb)) == [public]


def test_rejected_symlink_escape_does_not_enumerate_outside_directory(
    tmp_path, monkeypatch
):
    kb = tmp_path / "kb"
    kb.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("outside content")
    (kb / "escape").symlink_to(outside, target_is_directory=True)
    operations = TraceOperations(CollectionRegistry({"docs": kb}))
    original = os.scandir
    scans = []

    def scan(path):
        scans.append(Path(path).resolve())
        return original(path)

    monkeypatch.setattr(os, "scandir", scan)
    with pytest.raises(DocumentNotFoundError):
        operations.get_document("escape/secret.md")
    assert outside not in scans
