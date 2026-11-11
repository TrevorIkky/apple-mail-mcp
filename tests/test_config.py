"""Tests for IMAP account configuration."""

from __future__ import annotations

import json

import pytest

from apple_mail_mcp import config
from apple_mail_mcp.errors import ConfigError


def write_config(tmp_path, data):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data))
    return path


def test_missing_file_explains_how_to_create_one(tmp_path):
    with pytest.raises(ConfigError, match="No IMAP config"):
        config.load_account("work", tmp_path / "absent.json")


def test_invalid_json_names_the_file(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not json")
    with pytest.raises(ConfigError, match="not valid JSON"):
        config.load_account("work", path)


def test_unknown_account_lists_the_known_ones(tmp_path):
    path = write_config(tmp_path, {"accounts": {"home": {"host": "h", "user": "u"}}})
    with pytest.raises(ConfigError, match="Configured: home"):
        config.load_account("work", path)


def test_missing_fields_are_reported(tmp_path):
    path = write_config(tmp_path, {"accounts": {"work": {"host": "imap.example.com"}}})
    with pytest.raises(ConfigError, match="missing: user"):
        config.load_account("work", path)


def test_defaults_port_and_keychain_account(tmp_path):
    path = write_config(
        tmp_path,
        {"accounts": {"work": {"host": "imap.example.com", "user": "you@example.com"}}},
    )
    account = config.load_account("work", path)
    assert account.port == 993
    assert account.keychain_key == ("apple-mail-mcp", "you@example.com")


def test_explicit_keychain_entry_wins(tmp_path):
    path = write_config(
        tmp_path,
        {
            "accounts": {
                "work": {
                    "host": "imap.example.com",
                    "user": "you@example.com",
                    "keychain_service": "custom",
                    "keychain_account": "alias",
                }
            }
        },
    )
    assert config.load_account("work", path).keychain_key == ("custom", "alias")


def test_keychain_miss_explains_how_to_add_the_item(monkeypatch, tmp_path):
    path = write_config(
        tmp_path,
        {"accounts": {"work": {"host": "imap.example.com", "user": "you@example.com"}}},
    )
    account = config.load_account("work", path)

    class Missing:
        returncode = 44
        stdout = ""

    monkeypatch.setattr(config.subprocess, "run", lambda *a, **k: Missing())
    with pytest.raises(ConfigError, match="add-generic-password"):
        config.keychain_password(account)
