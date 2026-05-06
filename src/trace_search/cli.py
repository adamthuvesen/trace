"""Command-line interface for Trace."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence

from trace_search.diagnostics import invalid_config_report, render_doctor_report
from trace_search.operations import TraceOperations

OperationsFactory = Callable[[], TraceOperations]
ServeRunner = Callable[[], None]


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trace",
        description="Local search for file-backed knowledge bases.",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("serve", help="start the Trace MCP server")

    search = subparsers.add_parser("search", help="smart search")
    search.add_argument("query")
    search.add_argument("--top-k", type=positive_int, default=10)
    search.add_argument("--collection")

    semantic = subparsers.add_parser("semantic-search", help="semantic search")
    semantic.add_argument("query")
    semantic.add_argument("--top-k", type=positive_int, default=10)
    semantic.add_argument("--collection")

    keyword = subparsers.add_parser("keyword-search", help="BM25 keyword search")
    keyword.add_argument("keyword")
    keyword.add_argument("--max-results", type=positive_int, default=20)
    keyword.add_argument("--collection")

    hybrid = subparsers.add_parser(
        "hybrid-search",
        help="hybrid semantic + keyword search",
    )
    hybrid.add_argument("query")
    hybrid.add_argument("--top-k", type=positive_int, default=10)
    hybrid.add_argument("--collection")

    get_document = subparsers.add_parser(
        "get-document",
        help="fetch a document by path",
    )
    get_document.add_argument("path")
    get_document.add_argument("--collection")

    list_documents = subparsers.add_parser("list-documents", help="list documents")
    list_documents.add_argument("--folder")
    list_documents.add_argument("--limit", type=positive_int, default=50)
    list_documents.add_argument("--collection")

    index_stats = subparsers.add_parser("index-stats", help="show index statistics")
    index_stats.add_argument("--collection")

    reindex = subparsers.add_parser("reindex", help="rebuild search indexes")
    reindex.add_argument("--collection")

    doctor = subparsers.add_parser("doctor", help="diagnose Trace setup")
    doctor.add_argument("sample_query", nargs="*")
    doctor.add_argument("--collection")

    return parser


def run_cli(
    argv: Sequence[str] | None = None,
    *,
    operations_factory: OperationsFactory = TraceOperations.from_settings,
    serve: ServeRunner | None = None,
) -> int:
    parse_argv = sys.argv[1:] if argv is None else list(argv)
    args = build_parser().parse_args(parse_argv)

    if args.command in (None, "serve"):
        if serve is None:
            raise ValueError("serve runner is required")
        serve()
        return 0

    try:
        operations = operations_factory()
        output = _dispatch(args, operations)
    except Exception as exc:
        if args.command == "doctor":
            print(render_doctor_report(invalid_config_report(str(exc))))
            return 1
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if output:
        print(output)
    return 0


def _dispatch(args: argparse.Namespace, operations: TraceOperations) -> str:
    match args.command:
        case "search":
            return operations.search(args.query, args.top_k, args.collection)
        case "semantic-search":
            return operations.semantic_search(args.query, args.top_k, args.collection)
        case "keyword-search":
            return operations.keyword_search(
                args.keyword,
                args.max_results,
                args.collection,
            )
        case "hybrid-search":
            return operations.search_hybrid(args.query, args.top_k, args.collection)
        case "get-document":
            return operations.get_document(args.path, args.collection)
        case "list-documents":
            return operations.list_documents(args.folder, args.limit, args.collection)
        case "index-stats":
            return operations.index_stats(args.collection)
        case "reindex":
            return operations.reindex(args.collection)
        case "doctor":
            sample_query = " ".join(args.sample_query).strip() or None
            return operations.doctor(
                sample_query=sample_query,
                collection=args.collection,
            )
        case _:
            raise ValueError(f"Unknown command: {args.command}")
