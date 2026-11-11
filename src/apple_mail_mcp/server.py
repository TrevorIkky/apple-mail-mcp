"""Apple Mail MCP server.

Read-only access to Mail.app (plus draft creation). Never sends mail.

Everything goes through osascript. Two performance rules learned the hard way:
  * never use AppleScript `whose` filters on a large mailbox - `messages whose
    id is N` walks the store and times out. Iterate by index instead.
  * never fetch `content` for a list; only for the handful of messages asked for.
"""

from __future__ import annotations

import email
import imaplib
import json
import os
import re
import subprocess
from contextlib import contextmanager
from email.header import decode_header
from typing import Any

from mcp.server.mcpserver import MCPServer

mcp = MCPServer("apple-mail")

FIELD = "<<<F>>>"
RECORD = "<<<R>>>"
DEFAULT_TIMEOUT = 180


class MailError(RuntimeError):
    pass


def _esc(value: str) -> str:
    """Escape a Python string for embedding in an AppleScript string literal."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _run(script: str, timeout: int = DEFAULT_TIMEOUT) -> str:
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
            "`limit`), or check that Mail.app is running."
        ) from exc
    if proc.returncode != 0:
        raise MailError(proc.stderr.strip() or "osascript failed")
    return proc.stdout


def _records(raw: str, field_count: int) -> list[list[str]]:
    out: list[list[str]] = []
    for chunk in raw.split(RECORD):
        chunk = chunk.strip("\n")
        if not chunk.strip():
            continue
        parts = chunk.split(FIELD)
        if len(parts) < field_count:
            continue
        out.append([p.strip() for p in parts[:field_count - 1]] + [parts[field_count - 1]])
    return out


def _mailbox_ref(account: str, mailbox: str) -> str:
    return f'mailbox "{_esc(mailbox)}" of account "{_esc(account)}"'


@mcp.tool()
def list_accounts() -> list[str]:
    """List the mail accounts configured in Mail.app."""
    raw = _run('tell application "Mail" to get name of every account', timeout=30)
    return [a.strip() for a in raw.strip().split(",") if a.strip()]


@mcp.tool()
def list_mailboxes(account: str) -> list[str]:
    """List the mailboxes (folders) of one account."""
    script = f'''tell application "Mail"
  set out to ""
  repeat with mb in (every mailbox of account "{_esc(account)}")
    set out to out & (name of mb) & "{RECORD}"
  end repeat
  return out
end tell'''
    raw = _run(script, timeout=60)
    return [r[0] for r in _records(raw, 1)]


@mcp.tool()
def list_messages(
    account: str,
    mailbox: str = "INBOX",
    scan: int = 60,
    limit: int = 40,
    sender_contains: str = "",
    subject_contains: str = "",
    unread_only: bool = False,
) -> list[dict[str, Any]]:
    """List message headers, newest first, without fetching bodies.

    `scan` is how many of the newest messages to look at; `limit` caps how many
    matches come back. Filters are case-insensitive substrings.
    """
    script = f'''tell application "Mail"
  set out to ""
  set msgs to messages of {_mailbox_ref(account, mailbox)}
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
    set out to out & (id of m) & "{FIELD}" & theSender & "{FIELD}" & theSubject & "{FIELD}" & ((date received of m) as string) & "{FIELD}" & wasRead & "{RECORD}"
  end repeat
  return out
end tell'''
    raw = _run(script)
    want_sender = sender_contains.lower()
    want_subject = subject_contains.lower()
    results: list[dict[str, Any]] = []
    for mid, sender, subject, date, read_state in _records(raw, 5):
        if want_sender and want_sender not in sender.lower():
            continue
        if want_subject and want_subject not in subject.lower():
            continue
        if unread_only and read_state.strip() != "unread":
            continue
        results.append(
            {
                "id": int(mid) if mid.isdigit() else mid,
                "sender": sender,
                "subject": subject,
                "date": date,
                "read": read_state.strip() == "read",
            }
        )
        if len(results) >= limit:
            break
    return results


@mcp.tool()
def read_messages(
    account: str,
    ids: list[int],
    mailbox: str = "INBOX",
    scan: int = 200,
    max_chars: int = 20000,
) -> list[dict[str, Any]]:
    """Read full bodies for specific message ids (from list_messages/search_messages).

    Scans the newest `scan` messages of the mailbox to locate them, so raise
    `scan` for older mail. Each body is truncated to `max_chars`.
    """
    if not ids:
        return []
    id_list = ", ".join(str(int(i)) for i in ids)
    script = f'''tell application "Mail"
  set wanted to {{{id_list}}}
  set found to 0
  set out to ""
  set msgs to messages of {_mailbox_ref(account, mailbox)}
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
      set out to out & mid & "{FIELD}" & (sender of m) & "{FIELD}" & (subject of m) & "{FIELD}" & ((date received of m) as string) & "{FIELD}" & theBody & "{RECORD}"
      set found to found + 1
      if found is (count of wanted) then exit repeat
    end if
  end repeat
  return out
end tell'''
    raw = _run(script)
    out = []
    for mid, sender, subject, date, body in _records(raw, 5):
        out.append(
            {
                "id": int(mid) if mid.isdigit() else mid,
                "sender": sender,
                "subject": subject,
                "date": date,
                "body": body[:max_chars],
                "truncated": len(body) > max_chars,
            }
        )
    return out


@mcp.tool()
def read_by_position(
    account: str,
    positions: list[int],
    mailbox: str = "INBOX",
    max_chars: int = 20000,
) -> list[dict[str, Any]]:
    """Read bodies by position in the mailbox (1 = newest), skipping the id scan.

    `list_messages` returns messages in this order, so position 1 is its first
    result. Prefer this over `read_messages` on slow mailboxes such as Sent,
    where quoted threads make an id scan time out.
    """
    if not positions:
        return []
    pos_list = ", ".join(str(int(p)) for p in positions)
    script = f'''tell application "Mail"
  set out to ""
  set msgs to messages of {_mailbox_ref(account, mailbox)}
  set total to count of msgs
  repeat with p in {{{pos_list}}}
    if p <= total then
      set m to item p of msgs
      set theBody to ""
      try
        set theBody to content of m
      end try
      set out to out & (id of m) & "{FIELD}" & (sender of m) & "{FIELD}" & (subject of m) & "{FIELD}" & ((date received of m) as string) & "{FIELD}" & theBody & "{RECORD}"
    end if
  end repeat
  return out
end tell'''
    raw = _run(script)
    out = []
    for mid, sender, subject, date, body in _records(raw, 5):
        out.append(
            {
                "id": int(mid) if mid.isdigit() else mid,
                "sender": sender,
                "subject": subject,
                "date": date,
                "body": body[:max_chars],
                "truncated": len(body) > max_chars,
            }
        )
    return out


@mcp.tool()
def search_messages(
    account: str,
    query: str,
    mailbox: str = "INBOX",
    scan: int = 120,
    limit: int = 25,
    search_body: bool = False,
    max_chars: int = 4000,
) -> list[dict[str, Any]]:
    """Find messages whose sender or subject contains `query` (case-insensitive).

    `search_body: true` also searches bodies and returns an excerpt - much
    slower, so keep `scan` small when you use it.
    """
    body_clause = ""
    if search_body:
        body_clause = '''
      try
        set theBody to content of m
      end try'''
    script = f'''tell application "Mail"
  set out to ""
  set msgs to messages of {_mailbox_ref(account, mailbox)}
  set n to count of msgs
  if n > {int(scan)} then set n to {int(scan)}
  repeat with i from 1 to n
    set m to item i of msgs
    set theBody to ""{body_clause}
    set out to out & (id of m) & "{FIELD}" & (sender of m) & "{FIELD}" & (subject of m) & "{FIELD}" & ((date received of m) as string) & "{FIELD}" & theBody & "{RECORD}"
  end repeat
  return out
end tell'''
    raw = _run(script)
    needle = query.lower()
    results = []
    for mid, sender, subject, date, body in _records(raw, 5):
        haystack = f"{sender}\n{subject}"
        if search_body:
            haystack += f"\n{body}"
        if needle and needle not in haystack.lower():
            continue
        entry = {
            "id": int(mid) if mid.isdigit() else mid,
            "sender": sender,
            "subject": subject,
            "date": date,
        }
        if search_body:
            entry["excerpt"] = body[:max_chars]
        results.append(entry)
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

    `account` picks the sending address (an account name from list_accounts).
    """
    lines = [
        'tell application "Mail"',
        f'  set msg to make new outgoing message with properties {{subject:"{_esc(subject)}", content:"{_esc(body)}", visible:false}}',
    ]
    if account:
        lines.append(
            f'  try\n    set sender of msg to (email addresses of account "{_esc(account)}") as string\n  end try'
        )
    lines.append("  tell msg")
    for address in to:
        lines.append(
            f'    make new to recipient at end of to recipients with properties {{address:"{_esc(address)}"}}'
        )
    for address in cc or []:
        lines.append(
            f'    make new cc recipient at end of cc recipients with properties {{address:"{_esc(address)}"}}'
        )
    lines.append("  end tell")
    lines.append("  save msg")
    lines.append('  return "saved"')
    lines.append("end tell")
    _run("\n".join(lines), timeout=60)
    return f"Draft saved in Mail: {subject!r} to {', '.join(to)}"


# --------------------------------------------------------------------------
# IMAP backend (opt-in, fast)
#
# Apple exposes no supported framework for reading a mailbox from outside Mail
# (MailKit is an extension API; the on-disk store needs Full Disk Access and is
# undocumented). The supported AppleScript route above is bound by the ~2-minute
# Apple Event timeout, so for large mailboxes and server-side search we talk
# IMAP to the same account instead.
#
# Credentials never live in this repo: configure hosts in
# ~/.config/apple-mail-mcp/config.json and keep each password in the macOS
# Keychain, e.g.
#   security add-generic-password -s apple-mail-mcp -a you@example.com -w
# --------------------------------------------------------------------------

CONFIG_PATH = os.path.expanduser("~/.config/apple-mail-mcp/config.json")


def _load_config() -> dict[str, Any]:
    if not os.path.exists(CONFIG_PATH):
        raise MailError(
            f"No IMAP config at {CONFIG_PATH}. Create it with an entry per account: "
            '{"accounts": {"amband.co.ke": {"host": "mail.amband.co.ke", "port": 993, '
            '"user": "you@amband.co.ke", "keychain_service": "apple-mail-mcp", '
            '"keychain_account": "you@amband.co.ke"}}}'
        )
    with open(CONFIG_PATH) as fh:
        return json.load(fh)


def _keychain_password(service: str, account: str) -> str:
    proc = subprocess.run(
        ["security", "find-generic-password", "-s", service, "-a", account, "-w"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise MailError(
            f"No Keychain item for service {service!r} / account {account!r}. "
            f"Add one with: security add-generic-password -s {service} -a {account} -w"
        )
    return proc.stdout.strip()


@contextmanager
def _imap(account: str):
    cfg = _load_config().get("accounts", {}).get(account)
    if not cfg:
        raise MailError(f"No IMAP config for account {account!r} in {CONFIG_PATH}")
    password = cfg.get("password") or _keychain_password(
        cfg.get("keychain_service", "apple-mail-mcp"),
        cfg.get("keychain_account", cfg["user"]),
    )
    conn = imaplib.IMAP4_SSL(cfg["host"], int(cfg.get("port", 993)))
    try:
        conn.login(cfg["user"], password)
        yield conn
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def _decode(value: str | None) -> str:
    if not value:
        return ""
    out = []
    for text, charset in decode_header(value):
        if isinstance(text, bytes):
            out.append(text.decode(charset or "utf-8", errors="replace"))
        else:
            out.append(text)
    return "".join(out)


def _plain_body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(
                part.get("Content-Disposition", "")
            ):
                payload = part.get_payload(decode=True) or b""
                return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True) or b""
                html = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                return re.sub(r"<[^>]+>", " ", html)
        return ""
    payload = msg.get_payload(decode=True) or b""
    return payload.decode(msg.get_content_charset() or "utf-8", errors="replace")


@mcp.tool()
def imap_mailboxes(account: str) -> list[str]:
    """List IMAP folders for a configured account (fast path, needs config + Keychain)."""
    with _imap(account) as conn:
        status, data = conn.list()
        if status != "OK":
            raise MailError("IMAP LIST failed")
        return [line.decode(errors="replace").split(' "/" ')[-1].strip('"') for line in data]


@mcp.tool()
def imap_search(
    account: str,
    mailbox: str = "INBOX",
    from_contains: str = "",
    subject_contains: str = "",
    text_contains: str = "",
    since: str = "",
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Server-side search - fast even on huge mailboxes, unlike the AppleScript path.

    `since` takes IMAP date form, e.g. "01-Oct-2026". Returns headers plus the
    UIDs to pass to imap_fetch.
    """
    criteria: list[str] = []
    if from_contains:
        criteria += ["FROM", from_contains]
    if subject_contains:
        criteria += ["SUBJECT", subject_contains]
    if text_contains:
        criteria += ["TEXT", text_contains]
    if since:
        criteria += ["SINCE", since]
    if not criteria:
        criteria = ["ALL"]
    with _imap(account) as conn:
        conn.select(f'"{mailbox}"', readonly=True)
        status, data = conn.uid("search", None, *criteria)
        if status != "OK":
            raise MailError(f"IMAP SEARCH failed: {data}")
        uids = data[0].split()[-limit:][::-1]
        if not uids:
            return []
        status, fetched = conn.uid(
            "fetch",
            b",".join(uids),
            "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE TO CC)])",
        )
        out = []
        index = 0
        for item in fetched:
            if not isinstance(item, tuple):
                continue
            msg = email.message_from_bytes(item[1])
            out.append(
                {
                    "uid": uids[index].decode(),
                    "from": _decode(msg.get("From")),
                    "to": _decode(msg.get("To")),
                    "cc": _decode(msg.get("Cc")),
                    "subject": _decode(msg.get("Subject")),
                    "date": _decode(msg.get("Date")),
                }
            )
            index += 1
        return out


@mcp.tool()
def imap_fetch(
    account: str,
    uids: list[str],
    mailbox: str = "INBOX",
    max_chars: int = 20000,
) -> list[dict[str, Any]]:
    """Fetch full message bodies by UID (from imap_search). Read-only; does not mark as read."""
    if not uids:
        return []
    with _imap(account) as conn:
        conn.select(f'"{mailbox}"', readonly=True)
        out = []
        for uid in uids:
            status, data = conn.uid("fetch", uid.encode(), "(BODY.PEEK[])")
            if status != "OK" or not data or not isinstance(data[0], tuple):
                continue
            msg = email.message_from_bytes(data[0][1])
            body = _plain_body(msg)
            out.append(
                {
                    "uid": uid,
                    "from": _decode(msg.get("From")),
                    "to": _decode(msg.get("To")),
                    "cc": _decode(msg.get("Cc")),
                    "subject": _decode(msg.get("Subject")),
                    "date": _decode(msg.get("Date")),
                    "body": body[:max_chars],
                    "truncated": len(body) > max_chars,
                }
            )
        return out


def main() -> None:
    """Entry point: `apple-mail-mcp` (stdio), or `apple-mail-mcp --selftest`."""
    import sys

    if "--selftest" in sys.argv:
        accounts = list_accounts()
        print(json.dumps({"accounts": accounts}, indent=2))
        if accounts:
            msgs = list_messages(account=accounts[0], scan=10, limit=5)
            print(json.dumps(msgs, indent=2)[:2000])
        sys.exit(0)

    mcp.run()


if __name__ == "__main__":
    main()
