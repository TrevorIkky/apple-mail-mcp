"""Tests for the IMAP backend's parsing and criteria building."""

from __future__ import annotations

import email

from apple_mail_mcp.backends import imap


def message_from(text: str):
    return email.message_from_string(text)


def test_decode_mime_handles_encoded_words():
    assert imap.decode_mime("=?utf-8?q?Caf=C3=A9?=") == "Café"


def test_decode_mime_passes_plain_text_through():
    assert imap.decode_mime("Plain Subject") == "Plain Subject"


def test_decode_mime_of_none_is_empty():
    assert imap.decode_mime(None) == ""


def test_plain_body_single_part():
    msg = message_from("Subject: x\n\nhello there")
    assert imap.plain_body(msg) == "hello there"


def test_plain_body_prefers_text_plain_in_multipart():
    raw = (
        "Subject: x\n"
        'Content-Type: multipart/alternative; boundary="b"\n\n'
        "--b\nContent-Type: text/plain\n\nthe plain one\n"
        "--b\nContent-Type: text/html\n\n<p>the html one</p>\n"
        "--b--\n"
    )
    assert "the plain one" in imap.plain_body(message_from(raw))


def test_plain_body_falls_back_to_stripped_html():
    raw = (
        "Subject: x\n"
        'Content-Type: multipart/alternative; boundary="b"\n\n'
        "--b\nContent-Type: text/html\n\n<p>only <b>html</b></p>\n"
        "--b--\n"
    )
    body = imap.plain_body(message_from(raw))
    assert "only" in body and "html" in body and "<p>" not in body


def test_plain_body_skips_plain_text_attachments():
    raw = (
        "Subject: x\n"
        'Content-Type: multipart/mixed; boundary="b"\n\n'
        "--b\nContent-Type: text/plain\n"
        'Content-Disposition: attachment; filename="notes.txt"\n\nattached text\n'
        "--b\nContent-Type: text/plain\n\nreal body\n"
        "--b--\n"
    )
    assert imap.plain_body(message_from(raw)).strip() == "real body"


def test_build_criteria_defaults_to_all():
    assert imap.build_criteria("", "", "", "") == ["ALL"]


def test_build_criteria_combines_terms_in_order():
    assert imap.build_criteria("ann", "invoice", "", "01-Oct-2026") == [
        "FROM",
        "ann",
        "SUBJECT",
        "invoice",
        "SINCE",
        "01-Oct-2026",
    ]


def test_fetch_without_uids_does_not_connect(monkeypatch):
    monkeypatch.setattr(
        imap, "connect", lambda *a, **k: (_ for _ in ()).throw(AssertionError("connected"))
    )
    assert imap.fetch("work", "INBOX", [], max_chars=10) == []
