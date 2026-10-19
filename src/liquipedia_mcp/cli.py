"""Command line entry point: ``liquipedia-mcp``."""

from __future__ import annotations

import argparse
import ipaddress
import logging
import sys

from liquipedia_mcp import __version__
from liquipedia_mcp.client import LiquipediaClient
from liquipedia_mcp.errors import ConfigurationError


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="liquipedia-mcp",
        description=(
            "MCP server for the Liquipedia LPDB v3 API. Needs LIQUIPEDIA_API_KEY and "
            "LIQUIPEDIA_USER_AGENT in the environment. Data: Liquipedia, CC-BY-SA 3.0."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="stdio (default) or streamable-http",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind address (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="HTTP port (default 8000)")
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help=(
            "Allow binding HTTP to a non-loopback address. Anyone who can reach it uses YOUR "
            "API key; never expose it to the internet."
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging to stderr")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        stream=sys.stderr,
        format="%(levelname)s %(name)s: %(message)s",
    )
    remote = args.transport == "streamable-http" and not _is_loopback(args.host)
    if remote and not args.allow_remote:
        print(
            f"Refusing to bind to {args.host}: the server would let others spend your API key. "
            "Use 127.0.0.1, or pass --allow-remote if it is only reachable from your own "
            "private network.",
            file=sys.stderr,
        )
        return 2
    try:
        client = LiquipediaClient.from_env()
    except ConfigurationError as exc:
        print(f"liquipedia-mcp: {exc}", file=sys.stderr)
        return 2

    from liquipedia_mcp.server import build_server

    server = build_server(client)
    if args.transport == "stdio":
        server.run("stdio")
    else:
        server.run("streamable-http", host=args.host, port=args.port)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
