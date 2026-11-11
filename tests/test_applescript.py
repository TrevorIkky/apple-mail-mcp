"""Tests for the AppleScript backend's pure parts - no Mail.app required."""

from __future__ import annotations

import pytest

from apple_mail_mcp.backends import applescript as backend


def record(*fields: str) -> str:
    return backend.FIELD.join(fields) + backend.RECORD


def test_escape_quotes_and_backslashes():
    assert backend.escape('say "hi"') == 'say \\"hi\\"'
    assert backend.escape("back\\slash") == "back\\\\slash"


def test_escape_runs_before_quoting_in_mailbox_ref():
    ref = backend.mailbox_ref("work", 'Odd"name')
    assert ref == 'mailbox "Odd\\"name" of account "work"'


def test_parse_records_splits_fields():
    raw = record("1", "a@example.com", "Subject", "today", "body") + record(
        "2", "b@example.com", "Other", "today", "body two"
    )
    parsed = backend.parse_records(raw, 5)
    assert [row[0] for row in parsed] == ["1", "2"]
    assert parsed[0][1] == "a@example.com"


def test_parse_records_preserves_body_whitespace():
    raw = record("1", "a@example.com", "Subject", "today", "   indented body")
    assert backend.parse_records(raw, 5)[0][4] == "   indented body"


def test_parse_records_keeps_delimiters_inside_a_body():
    """A body containing newlines must not split into extra records."""
    raw = record("1", "a@example.com", "Subject", "today", "line one\nline two")
    parsed = backend.parse_records(raw, 5)
    assert len(parsed) == 1
    assert parsed[0][4] == "line one\nline two"


def test_parse_records_skips_short_rows():
    raw = record("1", "only", "three") + record("2", "a", "b", "c", "d")
    assert len(backend.parse_records(raw, 5)) == 1


def test_parse_records_ignores_trailing_blank():
    assert backend.parse_records(backend.RECORD + "\n", 5) == []


def test_run_raises_mail_error_on_failure(monkeypatch):
    class Failed:
        returncode = 1
        stdout = ""
        stderr = "Mail got an error: AppleEvent timed out. (-1712)"

    monkeypatch.setattr(backend.subprocess, "run", lambda *a, **k: Failed())
    with pytest.raises(backend.MailError, match="timed out"):
        backend.run("noop")


def test_run_wraps_script_in_timeout(monkeypatch):
    seen = {}

    class Ok:
        returncode = 0
        stdout = "fine"
        stderr = ""

    def fake_run(cmd, **kwargs):
        seen["input"] = kwargs["input"]
        return Ok()

    monkeypatch.setattr(backend.subprocess, "run", fake_run)
    backend.run('tell application "Mail" to noop', timeout=42)
    assert seen["input"].startswith("with timeout of 42 seconds")
    assert seen["input"].endswith("end timeout")


def test_read_by_ids_short_circuits_without_ids(monkeypatch):
    monkeypatch.setattr(backend, "run", lambda *a, **k: pytest.fail("should not call osascript"))
    assert backend.read_by_ids("work", "INBOX", [], scan=10, max_chars=100) == []


def test_read_by_position_truncates_and_flags(monkeypatch):
    raw = record("7", "a@example.com", "Subject", "today", "x" * 50)
    monkeypatch.setattr(backend, "run", lambda *a, **k: raw)
    [message] = backend.read_by_position("work", "INBOX", [1], max_chars=10)
    assert message["body"] == "x" * 10
    assert message["truncated"] is True
    assert message["id"] == 7


def test_scan_bound_is_interpolated_as_an_integer(monkeypatch):
    """`scan` must reach AppleScript as a literal number, never user text."""
    seen = {}
    monkeypatch.setattr(backend, "run", lambda script, **k: seen.setdefault("s", script) or "")
    backend.list_headers("work", "INBOX", scan=7)
    assert "if n > 7 then set n to 7" in seen["s"]
