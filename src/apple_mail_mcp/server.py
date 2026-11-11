"""Server assembly: build the MCP server and register both tool sets."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from .tools import imap_tools, mail_tools

INSTRUCTIONS = """Read Apple Mail on macOS.

Start with list_accounts, then list_messages for headers, then read_messages (or
read_by_position) for the few bodies you actually need - never fetch bodies in
bulk. On a large mailbox prefer imap_search when it is configured.

The only write available is create_draft, which saves a draft for the person to
review. Nothing here sends mail.
"""


def build_server() -> MCPServer:
    mcp = MCPServer("apple-mail", instructions=INSTRUCTIONS)
    mail_tools.register(mcp)
    imap_tools.register(mcp)
    return mcp
