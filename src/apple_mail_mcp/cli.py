"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import sys

from .backends import applescript
from .errors import MailError
from .server import build_server


def _selftest() -> int:
    """Check that Mail is reachable and the AppleScript backend works."""
    accounts = applescript.list_accounts()
    print(json.dumps({"accounts": accounts}, indent=2))
    if not accounts:
        print("No accounts found in Mail.app.", file=sys.stderr)
        return 1
    headers = applescript.list_headers(accounts[0], "INBOX", scan=5)
    print(json.dumps(headers, indent=2)[:2000])
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="apple-mail-mcp",
        description="MCP server for reading Apple Mail on macOS.",
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="print the configured accounts and the newest messages, then exit",
    )
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "sse", "streamable-http"],
        help="MCP transport to serve on (default: stdio)",
    )
    args = parser.parse_args(argv)

    try:
        if args.selftest:
            return _selftest()
        build_server().run(transport=args.transport)
    except MailError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
