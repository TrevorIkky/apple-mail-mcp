"""MCP tools backed by IMAP. Opt-in: they need config + a Keychain entry."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from ..backends import imap
from ..models import ImapHeader, ImapMessage


def register(mcp: MCPServer) -> None:
    """Attach the IMAP tools to the server."""

    @mcp.tool()
    def imap_mailboxes(account: str) -> list[str]:
        """List IMAP folders for a configured account.

        `account` is a key under "accounts" in ~/.config/apple-mail-mcp/config.json,
        not necessarily the name Mail.app shows.
        """
        return imap.list_mailboxes(account)

    @mcp.tool()
    def imap_search(
        account: str,
        mailbox: str = "INBOX",
        from_contains: str = "",
        subject_contains: str = "",
        text_contains: str = "",
        since: str = "",
        limit: int = 30,
    ) -> list[ImapHeader]:
        """Server-side search - fast even on mailboxes too large for AppleScript.

        `since` takes the IMAP date form, e.g. "01-Oct-2026". Returns headers
        plus the UIDs to pass to `imap_fetch`. Read-only: nothing is marked read.
        """
        criteria = imap.build_criteria(from_contains, subject_contains, text_contains, since)
        return imap.search(account, mailbox, criteria, limit)

    @mcp.tool()
    def imap_fetch(
        account: str,
        uids: list[str],
        mailbox: str = "INBOX",
        max_chars: int = 20000,
    ) -> list[ImapMessage]:
        """Fetch full message bodies by UID, as returned by `imap_search`."""
        return imap.fetch(account, mailbox, uids, max_chars)
