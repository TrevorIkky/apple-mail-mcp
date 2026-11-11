"""Backends: AppleScript (supported, default) and IMAP (fast, opt-in)."""

from . import applescript, imap

__all__ = ["applescript", "imap"]
