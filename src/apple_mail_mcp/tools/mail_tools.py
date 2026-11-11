"""MCP tools backed by AppleScript. Docstrings here are the model-facing API."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from ..backends import applescript
from ..models import Message, MessageHeader


def register(mcp: MCPServer) -> None:
    """Attach the AppleScript tools to the server."""

    @mcp.tool()
    def list_accounts() -> list[str]:
        """List the mail accounts configured in Mail.app."""
        return applescript.list_accounts()

    @mcp.tool()
    def list_mailboxes(account: str) -> list[str]:
        """List the mailboxes (folders) of one account.

        Names differ between accounts - INBOX on some, Inbox on others - so check
        here before guessing.
        """
        return applescript.list_mailboxes(account)

    @mcp.tool()
    def list_messages(
        account: str,
        mailbox: str = "INBOX",
        scan: int = 60,
        limit: int = 40,
        sender_contains: str = "",
        subject_contains: str = "",
        unread_only: bool = False,
    ) -> list[MessageHeader]:
        """List message headers, newest first, without fetching bodies.

        `scan` bounds how many of the newest messages are examined; `limit` caps
        how many matches come back. Filters are case-insensitive substrings.
        Positions in this result feed `read_by_position`.
        """
        headers = applescript.list_headers(account, mailbox, scan)
        want_sender = sender_contains.lower()
        want_subject = subject_contains.lower()
        matches: list[MessageHeader] = []
        for header in headers:
            if want_sender and want_sender not in header["sender"].lower():
                continue
            if want_subject and want_subject not in header["subject"].lower():
                continue
            if unread_only and header.get("read", True):
                continue
            matches.append(header)
            if len(matches) >= limit:
                break
        return matches

    @mcp.tool()
    def read_messages(
        account: str,
        ids: list[int],
        mailbox: str = "INBOX",
        scan: int = 200,
        max_chars: int = 20000,
    ) -> list[Message]:
        """Read full bodies for specific message ids from `list_messages`.

        Locates them by scanning the newest `scan` messages, so raise `scan` for
        older mail. If this times out, use `read_by_position` instead.
        """
        return applescript.read_by_ids(account, mailbox, ids, scan, max_chars)

    @mcp.tool()
    def read_by_position(
        account: str,
        positions: list[int],
        mailbox: str = "INBOX",
        max_chars: int = 20000,
    ) -> list[Message]:
        """Read full bodies by position in the mailbox, where 1 is the newest.

        `list_messages` returns messages in this order. Prefer this on mailboxes
        with long quoted threads - Sent, typically - where locating a message by
        id is slow enough to time out.
        """
        return applescript.read_by_position(account, mailbox, positions, max_chars)

    @mcp.tool()
    def search_messages(
        account: str,
        query: str,
        mailbox: str = "INBOX",
        scan: int = 120,
        limit: int = 25,
        search_body: bool = False,
        max_chars: int = 4000,
    ) -> list[dict]:
        """Find messages whose sender or subject contains `query`, case-insensitively.

        `search_body: true` also searches bodies and returns an excerpt, which is
        much slower - keep `scan` small. For real search on a large mailbox, use
        `imap_search`.
        """
        rows = applescript.scan_for_search(account, mailbox, scan, search_body)
        needle = query.lower()
        results: list[dict] = []
        for message_id, sender, subject, date, body in rows:
            haystack = f"{sender}\n{subject}"
            if search_body:
                haystack = f"{haystack}\n{body}"
            if needle and needle not in haystack.lower():
                continue
            hit: dict = {
                "id": int(message_id) if message_id.isdigit() else message_id,
                "sender": sender,
                "subject": subject,
                "date": date,
            }
            if search_body:
                hit["excerpt"] = body[:max_chars]
            results.append(hit)
            if len(results) >= limit:
                break
        return results

    @mcp.tool()
    def create_draft(
        subject: str,
        body: str,
        to: list[str],
        cc: list[str] | None = None,
        account: str = "",
    ) -> str:
        """Save a new message as a draft in Mail.app. It is never sent.

        `account` picks the sending address (an account name from
        `list_accounts`). The person reviews and sends the draft themselves.
        """
        applescript.create_draft(subject, body, to, cc, account)
        return f"Draft saved in Mail: {subject!r} to {', '.join(to)}"
