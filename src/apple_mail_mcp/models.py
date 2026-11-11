"""Shapes returned by the tools.

These are plain TypedDicts so the MCP layer can serialise them directly and the
two backends agree on one vocabulary.
"""

from __future__ import annotations

from typing import NotRequired, TypedDict


class MessageHeader(TypedDict):
    """A message without its body - cheap to fetch in bulk."""

    id: int | str
    sender: str
    subject: str
    date: str
    read: NotRequired[bool]


class Message(MessageHeader):
    """A message with its body."""

    body: str
    truncated: bool


class ImapHeader(TypedDict):
    """An IMAP search hit, addressed by UID rather than Mail's local id."""

    uid: str
    sender: str
    to: str
    cc: str
    subject: str
    date: str


class ImapMessage(ImapHeader):
    body: str
    truncated: bool
