# Architecture

Trace captures local documents, publishes search indexes, and exposes shared operations through CLI and MCP adapters.
The [development guide](development.md) lists commands and checks.
The [retrieval guide](retrieval-modes.md) defines ranking behavior.

## Ownership

| Module | Owns |
| --- | --- |
| `config.py` | Validated settings, model specifications, collection configuration |
| `extraction/` | Supported formats, corpus visibility, frontmatter, chunk construction |
| `indexing/index_builder.py` | Source capture, incremental reuse, embedding, publication |
| `indexing/index_reader.py` | Current generation loading, retained snapshots, neighbor lookup |
| `indexing/index_store.py` | Persisted payload validation, immutable rows, writer lock, generation swap |
| `indexing/index_metadata.py` | Source inventory, build recipe, readability and compatibility decisions |
| `retrieval/search_types.py` | Document and chunk identity, filters, hits, score evidence, ordered responses |
| `retrieval/search.py` | BM25, semantic, hybrid, and adaptive ranking |
| `retrieval/formatting.py` | Render an existing ranking and its evidence |
| `collections/collection_registry.py` | Collection resources, shared backend, public compatibility methods |
| `collections/operations.py` | Application operations, collection selection, snapshot pinning, merge, neighbors, errors |
| `server/` | CLI parsing, MCP tools, transport configuration |
| `tools/eval/` | Validated evaluation inputs, measurement, manifests, comparisons, reporting |
| `tools/convert_to_markdown.py` | Conversion planning, destination validation, conversion provenance |

The dependency contracts reject runtime imports from `server/`.
They also reject indexing or extraction imports from retrieval and collections.
BM25 tokenization and model warmup therefore live in `indexing/`.
Their former module paths remain compatibility exports.

## Typed operations and public dictionaries

`TraceOperations.search_response()` returns `SearchResponse` with hits in final ranking order.
Each `SearchHit` carries `DocumentRef`, `ChunkRef`, metadata, content, and `ScoreEvidence`.
`ChunkRef` includes the collection, document path, generation, and chunk position.
Typed response rendering preserves the supplied order.
Legacy list-based context formatting retains its score sorting.

Existing search methods still return dictionaries or `AdaptiveSearchResult`.
`WikiIndexer` keeps its constructor, snapshot, build, and neighbor methods.
`CollectionRegistry` keeps its public methods as delegates to the shared operations.
`trace_search/__init__.py` exposes the public imports and typed retrieval records.

Registry construction captures a settings copy.
Existing registries and indexers therefore retain their configuration when later environment variables change.
An injected embedding backend supplies its actual model name, dimensions, and runtime identity.
Persisted compatibility checks and query cache keys use that identity.

## Index lifecycle

`IndexBuilder` holds one writer lock for a physical index root.
It writes a complete `gen-*/` directory before atomically replacing `CURRENT`.
It synchronizes files and directories before publication.
A failed extraction or build leaves the previous generation available.

Changed files are extracted from captured bytes.
The builder checks each capture against the source inventory and checks for mutation during extraction.
This protects individual file captures.
It does not create an atomic snapshot of the whole knowledge base.
A file can change after its capture.
Unchanged files can reuse hashes when size and mtime match.
Use `reindex --force` after edits that preserve both values.

Each search operation retains one snapshot per collection.
Adaptive routing, hybrid candidates, filters, hits, and neighbor text use that snapshot.
Different collections can use different generations in the same request.
Readers notice a new `CURRENT` on a later request.
Loaded chunk records and embedding arrays resist mutation.

`get_document` reads the current source file.
`list_documents` also scans current files.
Their content can therefore differ from an earlier search snapshot until the next reindex.

## Index compatibility

Readability, query compatibility, and incremental reuse are separate decisions.

| Stored generation | Readable | Semantic query compatibility | Incremental reuse |
| --- | --- | --- | --- |
| Valid v7 | Yes | Actual model, dimensions, and runtime must match | Full recipe must match |
| Valid v6 | Explicit legacy decoder | Matching legacy ONNX identity can search it | No, next reindex rebuilds |
| Unknown schema or malformed payload | Error with rebuild guidance | Unavailable | Reindex rebuilds |

The v7 build recipe includes model identity, dimensions, backend, chunk size, overlap, BM25 parameters, tokenizer, and transformation versions.
Changed chunking or BM25 settings prevent reuse but do not invalidate the loaded vectors by themselves.
BM25 queries use the parameters persisted in the loaded artifact.
A mismatched embedding backend cannot query those vectors safely.
Semantic search rejects that mismatch and requests a reindex.

Run `trace reindex` after upgrading from v6 or changing the build recipe.
Use `--force` when every source must be extracted again.

## Errors and transport boundaries

`DocumentNotFoundError`, `DocumentReadError`, and `ReindexError` represent failed operations.
Expected CLI failures write an error to stderr and return a nonzero status.
MCP adapters expose failed tool calls through the protocol error flag.
Empty search results remain successful responses.

A multi-collection reindex can publish some collections before another fails.
`ReindexError` records completed and failed collections.
Publication is atomic within each collection, not across all collections.
`doctor` reports configuration and index problems without building an index for its sample query.

The HTTP server accepts loopback hosts and enables host and origin protection.
It is stateless and unauthenticated.
The same `create_mcp()` factory configures serving and inspection.
