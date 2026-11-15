"""Replay the directory durability failure fixed by 0875b29."""

from pathlib import Path

from tests.test_runtime_hardening import FakeBackend
from trace_search.indexing import index_store
from trace_search.indexing.wiki_indexer import WikiIndexer


def test_generation_directories_are_synced_before_current_changes(tmp_path, monkeypatch):
    kb = tmp_path / "documents"
    kb.mkdir()
    (kb / "intro.md").write_text("# Intro\n\nDurable publication fixture.")
    index_root = tmp_path / "index"
    events = []
    original_sync = index_store._fsync
    original_rename = Path.rename
    original_replace = index_store.os.replace

    def sync(path):
        original_sync(path)
        events.append(("directory" if path.is_dir() else "file", path))

    def rename(source, destination):
        events.append(("rename", source))
        return original_rename(source, destination)

    def replace(source, destination):
        events.append(("replace", Path(destination)))
        return original_replace(source, destination)

    monkeypatch.setattr(index_store, "_fsync", sync)
    monkeypatch.setattr(Path, "rename", rename)
    monkeypatch.setattr(index_store.os, "replace", replace)
    WikiIndexer(kb, index_root=index_root, backend=FakeBackend()).build_index()

    rename_position = next(i for i, event in enumerate(events) if event[0] == "rename")
    temporary_generation = events[rename_position][1]
    bm25_sync = events.index(("directory", temporary_generation / "bm25"))
    generation_sync = events.index(("directory", temporary_generation))
    pointer_replace = events.index(("replace", index_root / "CURRENT"))
    assert bm25_sync < generation_sync < rename_position < pointer_replace
    assert ("directory", index_root) in events[rename_position + 1 : pointer_replace]
    assert events[-1] == ("directory", index_root)
