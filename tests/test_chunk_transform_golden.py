"""Incremental builds reuse persisted chunks unless INDEX_METADATA_VERSION changes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tests.test_runtime_hardening import FakeBackend
from trace_search.config import Settings
from trace_search.indexing.index_metadata import INDEX_METADATA_VERSION
from trace_search.indexing.wiki_indexer import WikiIndexer

FIXTURE_KB = Path(__file__).parent / "fixtures" / "chunk_transform_kb"
GOLDEN_VERSION = 7
GOLDEN_FINGERPRINT = "aaa0cf84183160ecbd427391e5d51fc0fae5f05c777a2dd401bc0ec0f8f98568"


def _fingerprint(tmp_path: Path) -> str:
    config = Settings(char_chunk_size=300, char_overlap_size=60)
    builder = WikiIndexer(FIXTURE_KB, tmp_path, FakeBackend(), config=config).builder
    paths = sorted(
        str(path.relative_to(FIXTURE_KB))
        for path in FIXTURE_KB.rglob("*")
        if path.is_file()
    )
    ids, texts, chunks = builder._build_chunks(builder._load_documents_subset(paths))
    stable = [
        {key: value for key, value in chunk.items() if key != "source_mtime"}
        for chunk in chunks
    ]
    payload = json.dumps([ids, texts, stable], sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def test_chunk_transform_changes_bump_index_metadata_version(tmp_path):
    actual = _fingerprint(tmp_path)
    fix = (
        "Bump INDEX_METADATA_VERSION in src/trace_search/indexing/index_metadata.py, "
        "then set GOLDEN_VERSION to the new version and GOLDEN_FINGERPRINT to "
        f"{actual!r} in tests/test_chunk_transform_golden.py, in the same change. "
        "Otherwise incremental builds reuse chunks made by the old transform."
    )
    if actual != GOLDEN_FINGERPRINT:
        assert INDEX_METADATA_VERSION != GOLDEN_VERSION, (
            f"Chunk text or metadata changed. {fix}"
        )
    assert (INDEX_METADATA_VERSION, actual) == (GOLDEN_VERSION, GOLDEN_FINGERPRINT), (
        f"INDEX_METADATA_VERSION and the chunk golden must change together. {fix}"
    )
