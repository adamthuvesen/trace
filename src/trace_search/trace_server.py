"""Multi-collection trace MCP server entrypoint."""

import sys

from trace_search.diagnostics import (
    diagnose_collections,
    invalid_config_report,
    render_doctor_report,
)
from trace_search.config import get_settings
from trace_search.server_app import CollectionRegistry, build_multi_mcp


def run_doctor_cli(argv: list[str] | None = None) -> int:
    """Run Trace doctor from the console script."""
    args = list(argv or [])
    collection: str | None = None
    sample_query_parts: list[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--collection" and i + 1 < len(args):
            collection = args[i + 1]
            i += 2
            continue
        sample_query_parts.append(arg)
        i += 1

    sample_query = " ".join(sample_query_parts).strip() or None

    try:
        app_settings = get_settings()
        registry = CollectionRegistry(
            app_settings.parsed_collections,
            index_root=app_settings.index_path,
        )
        report = diagnose_collections(
            app_settings.parsed_collections,
            index_root=app_settings.index_path,
            sample_query=sample_query,
            sample_collection=collection,
            sample_query_runner=lambda query, col_name: registry.probe_search(
                query,
                5,
                col_name,
            ),
        )
    except Exception as exc:
        report = invalid_config_report(str(exc))

    print(render_doctor_report(report))
    return 0 if report.ok else 1


def main() -> None:
    """Run the multi-collection MCP server."""
    args = sys.argv[1:]
    if args and args[0] == "doctor":
        raise SystemExit(run_doctor_cli(args[1:]))

    mcp, _ = build_multi_mcp("trace", get_settings().parsed_collections)
    mcp.run()


if __name__ == "__main__":
    main()
