"""Allow `python -m apple_mail_mcp`."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
