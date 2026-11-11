"""IMAP backend - the fast path.

Independent of Mail.app: server-side SEARCH stays quick on mailboxes far larger
than the AppleScript bridge can walk. Requires configuration (see config.py).

Connections are read-only (``readonly=True``) and bodies are fetched with
``BODY.PEEK[]``, so reading here never marks a message as read.
"""

from __future__ import annotations

import email
import imaplib
import re
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from email.header import decode_header
from email.message import Message as EmailMessage

from ..config import ImapAccount, keychain_password, load_account
from ..errors import MailError
from ..models import ImapHeader, ImapMessage

HEADER_FIELDS = "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE TO CC)])"


@contextmanager
def connect(account_name: str) -> Iterator[imaplib.IMAP4_SSL]:
    account: ImapAccount = load_account(account_name)
    password = keychain_password(account)
    try:
        conn = imaplib.IMAP4_SSL(account.host, account.port)
    except OSError as exc:
        raise MailError(f"Cannot reach {account.host}:{account.port} - {exc}") from exc
    try:
        conn.login(account.user, password)
    except imaplib.IMAP4.error as exc:
        raise MailError(
            f"IMAP login failed for {account.user}. For Gmail and iCloud this must "
            f"be an app-specific password. ({exc})"
        ) from exc
    try:
        yield conn
    finally:
        # A failed logout tells the caller nothing useful; the socket closes anyway.
        with suppress(Exception):
            conn.logout()


def decode_mime(value: str | None) -> str:
    """Decode an RFC 2047 header into plain text."""
    if not value:
        return ""
    parts = []
    for text, charset in decode_header(value):
        if isinstance(text, bytes):
            parts.append(text.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(text)
    return "".join(parts)


def plain_body(message: EmailMessage) -> str:
    """Best-effort plain text: the text/plain part, else HTML with tags stripped."""
    if not message.is_multipart():
        payload = message.get_payload(decode=True) or b""
        return payload.decode(message.get_content_charset() or "utf-8", errors="replace")

    for part in message.walk():
        disposition = str(part.get("Content-Disposition", ""))
        if part.get_content_type() == "text/plain" and "attachment" not in disposition:
            payload = part.get_payload(decode=True) or b""
            return payload.decode(part.get_content_charset() or "utf-8", errors="replace")

    for part in message.walk():
        if part.get_content_type() == "text/html":
            payload = part.get_payload(decode=True) or b""
            html = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
            return re.sub(r"<[^>]+>", " ", html)
    return ""


def _header(message: EmailMessage, uid: str) -> ImapHeader:
    return ImapHeader(
        uid=uid,
        sender=decode_mime(message.get("From")),
        to=decode_mime(message.get("To")),
        cc=decode_mime(message.get("Cc")),
        subject=decode_mime(message.get("Subject")),
        date=decode_mime(message.get("Date")),
    )


def list_mailboxes(account: str) -> list[str]:
    with connect(account) as conn:
        status, data = conn.list()
        if status != "OK":
            raise MailError("IMAP LIST failed")
        return [line.decode(errors="replace").split(' "/" ')[-1].strip('"') for line in data]


def build_criteria(
    from_contains: str, subject_contains: str, text_contains: str, since: str
) -> list[str]:
    criteria: list[str] = []
    if from_contains:
        criteria += ["FROM", from_contains]
    if subject_contains:
        criteria += ["SUBJECT", subject_contains]
    if text_contains:
        criteria += ["TEXT", text_contains]
    if since:
        criteria += ["SINCE", since]
    return criteria or ["ALL"]


def search(
    account: str,
    mailbox: str,
    criteria: list[str],
    limit: int,
) -> list[ImapHeader]:
    with connect(account) as conn:
        conn.select(f'"{mailbox}"', readonly=True)
        status, data = conn.uid("search", None, *criteria)
        if status != "OK":
            raise MailError(f"IMAP SEARCH failed: {data!r}")
        uids = data[0].split()[-limit:][::-1]
        if not uids:
            return []
        status, fetched = conn.uid("fetch", b",".join(uids), HEADER_FIELDS)
        if status != "OK":
            raise MailError(f"IMAP FETCH failed: {fetched!r}")
        headers: list[ImapHeader] = []
        index = 0
        for item in fetched:
            if not isinstance(item, tuple):
                continue
            headers.append(_header(email.message_from_bytes(item[1]), uids[index].decode()))
            index += 1
        return headers


def fetch(account: str, mailbox: str, uids: list[str], max_chars: int) -> list[ImapMessage]:
    if not uids:
        return []
    with connect(account) as conn:
        conn.select(f'"{mailbox}"', readonly=True)
        messages: list[ImapMessage] = []
        for uid in uids:
            status, data = conn.uid("fetch", uid.encode(), "(BODY.PEEK[])")
            if status != "OK" or not data or not isinstance(data[0], tuple):
                continue
            parsed = email.message_from_bytes(data[0][1])
            body = plain_body(parsed)
            messages.append(
                ImapMessage(
                    **_header(parsed, uid),
                    body=body[:max_chars],
                    truncated=len(body) > max_chars,
                )
            )
        return messages
