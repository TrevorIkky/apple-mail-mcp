# Contributing

```bash
git clone https://github.com/TrevorIkky/apple-mail-mcp
cd apple-mail-mcp
uv run pytest            # tests - no Mail.app needed
uv run ruff check .
uv run ruff format .
uv run apple-mail-mcp --selftest   # needs macOS + Mail.app
```

## Layout

```
src/apple_mail_mcp/
  cli.py              argparse entry point (serve / --selftest)
  server.py           builds the MCPServer and registers tool sets
  config.py           IMAP account config + Keychain lookup
  errors.py           MailError, ConfigError
  models.py           TypedDicts both backends return
  backends/
    applescript.py    osascript: script building, running, parsing
    imap.py           IMAP: connect, search, fetch, MIME decoding
  tools/
    mail_tools.py     MCP tools over the AppleScript backend
    imap_tools.py     MCP tools over the IMAP backend
tests/                parsing, config and criteria-building tests
```

The split that matters: **backends do the talking, tools do the describing.**
A tool function should be thin — its docstring is the API the model reads, so
spend the words there, and keep the mechanics in the backend where they can be
tested without Mail.app running.

## Things to keep true

* **No `whose` filters in AppleScript.** `messages whose id is N` walks the whole
  store and blows the Apple Event timeout. Iterate by index, filter in Python.
* **Never fetch `content` for a list of messages.** Headers are cheap, bodies are
  not. One wedged Mail.app for four minutes during development.
* **Every entry point takes a `scan` bound**, interpolated with `int()`, so a
  request can't become a mailbox-wide walk and can't carry user text into a
  script.
* **Reads stay reads.** IMAP connects `readonly=True` and fetches with
  `BODY.PEEK[]`; nothing marks a message as read.
* **No sending.** `create_draft` is the only write, and it saves a draft for a
  person to review.
* **No secrets in the repo or in config files.** Passwords live in the Keychain.

## Tests

The suite covers the parts that don't need Mail: record parsing (including
bodies that contain newlines and leading whitespace), AppleScript escaping,
error messages, MIME decoding, multipart body selection, and config/Keychain
failures. Anything that would need a live mailbox belongs in `--selftest`
instead.
