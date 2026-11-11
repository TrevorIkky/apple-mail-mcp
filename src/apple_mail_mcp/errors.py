"""Error types surfaced to MCP clients."""

from __future__ import annotations


class MailError(RuntimeError):
    """Raised when Mail.app, osascript or IMAP cannot satisfy a request.

    The message is shown to the user of the MCP client, so it should say what to
    do next rather than only what went wrong.
    """


class ConfigError(MailError):
    """Raised when the IMAP configuration is missing or incomplete."""
