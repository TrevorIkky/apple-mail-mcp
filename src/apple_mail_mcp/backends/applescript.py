"""AppleScript backend - the route Apple documents.

Two rules are load-bearing here, both learned by wedging Mail for minutes at a
time:

* **No ``whose`` filters.** ``messages whose id is N`` walks the whole store and
  blows past the Apple Event timeout. Iterate by index and filter in Python.
* **Never fetch ``content`` for a list.** Headers are cheap, bodies are not.

Every entry point takes a ``scan`` bound so a request cannot quietly turn into a
mailbox-wide walk.
"""

from __future__ import annotations

import subprocess

from ..errors import MailError
from ..models import Message, MessageHeader

FIELD = "<<<F>>>"
RECORD = "<<<R>>>"
DEFAULT_TIMEOUT = 180
"""Seconds. Apple Events give up at ~120s; Mail often gives up sooner."""


def escape(value: str) -> str:
    """Escape a Python string for embedding in an AppleScript string literal."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def mailbox_ref(account: str, mailbox: str) -> str:
    return f'mailbox "{escape(mailbox)}" of account "{escape(account)}"'


def run(script: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    """Execute an AppleScript snippet and return its stdout."""
    wrapped = f"with timeout of {timeout} seconds\n{script}\nend timeout"
    try:
        proc = subprocess.run(
            ["osascript", "-"],
            input=wrapped,
            capture_output=True,
            text=True,
            timeout=timeout + 15,
        )
    except subprocess.TimeoutExpired as exc:
        raise MailError(
            "Mail did not answer in time. Narrow the request (smaller `scan` or "
            "`limit`), use `read_by_position` instead of `read_messages`, or "
            "configure the IMAP tools for this account."
        ) from exc
    if proc.returncode != 0:
        raise MailError(proc.stderr.strip() or "osascript failed")
    return proc.stdout


def parse_records(raw: str, field_count: int) -> list[list[str]]:
    """Split the delimited blob the scripts emit into records of ``field_count`` fields.

    The final field is left unstripped: it is the body, where leading whitespace
    is part of the message.
    """
    records: list[list[str]] = []
    for chunk in raw.split(RECORD):
        if not chunk.strip():
            continue
        parts = chunk.strip("\n").split(FIELD)
        if len(parts) < field_count:
            continue
        head = [part.strip() for part in parts[: field_count - 1]]
        records.append([*head, parts[field_count - 1]])
    return records


def _message_fields() -> str:
    """The AppleScript expression emitting one record with a body."""
    return (
        f'(id of m) & "{FIELD}" & (sender of m) & "{FIELD}" & (subject of m) & '
        f'"{FIELD}" & ((date received of m) as string) & "{FIELD}" & theBody & "{RECORD}"'
    )


def _header_fields() -> str:
    """The AppleScript expression emitting one header record (no body)."""
    return (
        f'(id of m) & "{FIELD}" & theSender & "{FIELD}" & theSubject & '
        f'"{FIELD}" & ((date received of m) as string) & "{FIELD}" & wasRead & "{RECORD}"'
    )


def _to_message(record: list[str], max_chars: int) -> Message:
    message_id, sender, subject, date, body = record
    return Message(
        id=int(message_id) if message_id.isdigit() else message_id,
        sender=sender,
        subject=subject,
        date=date,
        body=body[:max_chars],
        truncated=len(body) > max_chars,
    )


def list_accounts() -> list[str]:
    raw = run('tell application "Mail" to get name of every account', timeout=30)
    return [name.strip() for name in raw.strip().split(",") if name.strip()]


def list_mailboxes(account: str) -> list[str]:
    script = f'''tell application "Mail"
  set out to ""
  repeat with mb in (every mailbox of account "{escape(account)}")
    set out to out & (name of mb) & "{RECORD}"
  end repeat
  return out
end tell'''
    return [record[0] for record in parse_records(run(script, timeout=60), 1)]


def list_headers(account: str, mailbox: str, scan: int) -> list[MessageHeader]:
    """Newest-first headers for the newest ``scan`` messages. No bodies."""
    script = f"""tell application "Mail"
  set out to ""
  set msgs to messages of {mailbox_ref(account, mailbox)}
  set n to count of msgs
  if n > {int(scan)} then set n to {int(scan)}
  repeat with i from 1 to n
    set m to item i of msgs
    set theSender to ""
    set theSubject to ""
    try
      set theSender to sender of m
    end try
    try
      set theSubject to subject of m
    end try
    set wasRead to "read"
    try
      if read status of m is false then set wasRead to "unread"
    end try
    set out to out & {_header_fields()}
  end repeat
  return out
end tell"""
    headers: list[MessageHeader] = []
    for message_id, sender, subject, date, read_state in parse_records(run(script), 5):
        headers.append(
            MessageHeader(
                id=int(message_id) if message_id.isdigit() else message_id,
                sender=sender,
                subject=subject,
                date=date,
                read=read_state.strip() == "read",
            )
        )
    return headers


def read_by_ids(
    account: str, mailbox: str, ids: list[int], scan: int, max_chars: int
) -> list[Message]:
    """Bodies for specific ids, located by scanning the newest ``scan`` messages."""
    if not ids:
        return []
    id_list = ", ".join(str(int(value)) for value in ids)
    script = f"""tell application "Mail"
  set wanted to {{{id_list}}}
  set found to 0
  set out to ""
  set msgs to messages of {mailbox_ref(account, mailbox)}
  set n to count of msgs
  if n > {int(scan)} then set n to {int(scan)}
  repeat with i from 1 to n
    set m to item i of msgs
    set mid to id of m
    if wanted contains mid then
      set theBody to ""
      try
        set theBody to content of m
      end try
      set out to out & {_message_fields()}
      set found to found + 1
      if found is (count of wanted) then exit repeat
    end if
  end repeat
  return out
end tell"""
    return [_to_message(record, max_chars) for record in parse_records(run(script), 5)]


def read_by_position(
    account: str, mailbox: str, positions: list[int], max_chars: int
) -> list[Message]:
    """Bodies by position (1 = newest), skipping the id scan entirely.

    Mailboxes whose messages carry long quoted threads - Sent, typically - are
    slow enough that locating a message by id times out. Position is free.
    """
    if not positions:
        return []
    position_list = ", ".join(str(int(value)) for value in positions)
    script = f"""tell application "Mail"
  set out to ""
  set msgs to messages of {mailbox_ref(account, mailbox)}
  set total to count of msgs
  repeat with p in {{{position_list}}}
    if p <= total then
      set m to item p of msgs
      set theBody to ""
      try
        set theBody to content of m
      end try
      set out to out & {_message_fields()}
    end if
  end repeat
  return out
end tell"""
    return [_to_message(record, max_chars) for record in parse_records(run(script), 5)]


def scan_for_search(
    account: str, mailbox: str, scan: int, include_body: bool
) -> list[tuple[str, str, str, str, str]]:
    """Raw rows (id, sender, subject, date, body) for client-side searching."""
    body_clause = (
        """
      try
        set theBody to content of m
      end try"""
        if include_body
        else ""
    )
    script = f'''tell application "Mail"
  set out to ""
  set msgs to messages of {mailbox_ref(account, mailbox)}
  set n to count of msgs
  if n > {int(scan)} then set n to {int(scan)}
  repeat with i from 1 to n
    set m to item i of msgs
    set theBody to ""{body_clause}
    set out to out & {_message_fields()}
  end repeat
  return out
end tell'''
    return [tuple(record) for record in parse_records(run(script), 5)]  # type: ignore[misc]


def create_draft(
    subject: str, body: str, to: list[str], cc: list[str] | None, account: str
) -> None:
    """Save a draft in Mail. This module has no way to send one."""
    lines = [
        'tell application "Mail"',
        f"  set msg to make new outgoing message with properties "
        f'{{subject:"{escape(subject)}", content:"{escape(body)}", visible:false}}',
    ]
    if account:
        lines.append(
            "  try\n"
            f'    set sender of msg to (email addresses of account "{escape(account)}") as string\n'
            "  end try"
        )
    lines.append("  tell msg")
    for address in to:
        lines.append(
            "    make new to recipient at end of to recipients with properties "
            f'{{address:"{escape(address)}"}}'
        )
    for address in cc or []:
        lines.append(
            "    make new cc recipient at end of cc recipients with properties "
            f'{{address:"{escape(address)}"}}'
        )
    lines.extend(["  end tell", "  save msg", '  return "saved"', "end tell"])
    run("\n".join(lines), timeout=60)
