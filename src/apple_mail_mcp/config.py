"""IMAP account configuration and Keychain lookup.

Passwords are never stored in the config file. The file names a Keychain item;
the password is read from the macOS Keychain at connection time.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigError

DEFAULT_CONFIG_PATH = Path(
    os.environ.get("APPLE_MAIL_MCP_CONFIG", "~/.config/apple-mail-mcp/config.json")
).expanduser()

DEFAULT_KEYCHAIN_SERVICE = "apple-mail-mcp"

_EXAMPLE = """{
  "accounts": {
    "work": {
      "host": "imap.example.com",
      "port": 993,
      "user": "you@example.com",
      "keychain_service": "apple-mail-mcp",
      "keychain_account": "you@example.com"
    }
  }
}"""


@dataclass(frozen=True)
class ImapAccount:
    """Connection details for one IMAP account."""

    name: str
    host: str
    user: str
    port: int = 993
    keychain_service: str = DEFAULT_KEYCHAIN_SERVICE
    keychain_account: str = ""

    @property
    def keychain_key(self) -> tuple[str, str]:
        return self.keychain_service, self.keychain_account or self.user


def load_account(name: str, config_path: Path | None = None) -> ImapAccount:
    """Read one account's settings from the config file."""
    path = config_path or DEFAULT_CONFIG_PATH
    if not path.exists():
        raise ConfigError(
            f"No IMAP config at {path}. The AppleScript tools work without it; "
            f"for the IMAP tools create the file as:\n{_EXAMPLE}"
        )
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON: {exc}") from exc

    entry = data.get("accounts", {}).get(name)
    if not entry:
        known = ", ".join(sorted(data.get("accounts", {}))) or "none"
        raise ConfigError(f"No IMAP account named {name!r} in {path}. Configured: {known}")

    missing = [key for key in ("host", "user") if not entry.get(key)]
    if missing:
        raise ConfigError(f"Account {name!r} in {path} is missing: {', '.join(missing)}")

    return ImapAccount(
        name=name,
        host=entry["host"],
        user=entry["user"],
        port=int(entry.get("port", 993)),
        keychain_service=entry.get("keychain_service", DEFAULT_KEYCHAIN_SERVICE),
        keychain_account=entry.get("keychain_account", ""),
    )


def keychain_password(account: ImapAccount) -> str:
    """Read the account's password from the macOS Keychain."""
    service, keychain_account = account.keychain_key
    proc = subprocess.run(
        ["security", "find-generic-password", "-s", service, "-a", keychain_account, "-w"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise ConfigError(
            f"No Keychain item for service {service!r} / account {keychain_account!r}. "
            f"Add one with:\n  security add-generic-password -s {service} "
            f"-a {keychain_account} -w"
        )
    return proc.stdout.strip()
