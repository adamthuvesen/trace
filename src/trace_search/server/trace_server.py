"""Trace console entrypoint."""

from trace_search.server.cli import (
    DEFAULT_HTTP_HOST,
    DEFAULT_HTTP_PORT,
    ServeTransport,
    run_cli,
)
from trace_search.config import configure_logging, get_settings
from trace_search.server.mcp_tools import build_multi_mcp


def run_server(
    transport: ServeTransport = "stdio",
    host: str = DEFAULT_HTTP_HOST,
    port: int = DEFAULT_HTTP_PORT,
) -> None:
    """Run the Trace MCP server over stdio or streamable HTTP."""
    configure_logging()
    mcp, _ = build_multi_mcp("trace", get_settings().parsed_collections)
    if transport == "stdio":
        mcp.run()
        return
    mcp.run(
        transport="http",
        host=host,
        port=port,
        path="/mcp",
        # No server-side sessions, so restarting the shared daemon does not
        # strand connected clients holding a session id it no longer knows.
        stateless_http=True,
        # Reject DNS-rebinding requests from browser pages to this local,
        # unauthenticated server.
        host_origin_protection="auto",
    )


def main() -> None:
    """Run the Trace CLI."""
    raise SystemExit(run_cli(serve=run_server))


if __name__ == "__main__":
    main()
