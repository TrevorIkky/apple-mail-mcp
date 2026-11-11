# apple-mail-mcp

Let an AI assistant read your Apple Mail — search it, read threads, and save
drafts — instead of squinting at screenshots of the Mail window.

It is an [MCP](https://modelcontextprotocol.io) server for macOS. It talks to
Mail.app through AppleScript out of the box (no setup, no credentials), and can
optionally use IMAP for speed on big mailboxes.

**It never sends mail.** The only write it can do is save a draft.

---

## Quick start

You need macOS with Mail.app set up, and [uv](https://docs.astral.sh/uv/).

### Claude Code

```bash
claude mcp add apple-mail -s user -- uvx apple-mail-mcp
```

### Claude Desktop, or any MCP client

Add this to the client's MCP config (for Claude Desktop that is
`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "apple-mail": {
      "command": "uvx",
      "args": ["apple-mail-mcp"]
    }
  }
}
```

Restart the client. The first time the server talks to Mail, macOS asks you to
allow it to control Mail — say yes, or it can't read anything.

Then just ask: *"what did Jane send me last week?"*, *"summarise the thread about
the invoice"*, *"draft a reply agreeing to Tuesday"*.

### Check it works

```bash
uvx apple-mail-mcp --selftest
```

That prints your account names and the five newest messages in the first one.

---

## What it can do

| Tool | What it does |
| --- | --- |
| `list_accounts` | The accounts configured in Mail |
| `list_mailboxes` | Folders in an account |
| `list_messages` | Newest messages, headers only, with sender/subject/unread filters |
| `read_messages` | Full bodies for specific message ids |
| `search_messages` | Find by sender or subject (optionally body text) |
| `create_draft` | Save a draft in Mail — never sends |
| `imap_search` / `imap_fetch` / `imap_mailboxes` | The fast path, see below |

A typical sequence: `list_messages` to see what's there → `read_messages` with
the handful of ids that matter → `create_draft` for the reply.

---

## The fast path (optional)

AppleScript is the only route Apple documents, but every call is synchronous
against the Mail app and dies at the Apple Event timeout (~2 minutes). On a
mailbox with tens of thousands of messages, a broad search will simply time out.

If that's you, point the IMAP tools at the same account and get real server-side
search. Create `~/.config/apple-mail-mcp/config.json`:

```json
{
  "accounts": {
    "work": {
      "host": "imap.example.com",
      "port": 993,
      "user": "you@example.com",
      "keychain_service": "apple-mail-mcp",
      "keychain_account": "you@example.com"
    }
  }
}
```

Your password is not in that file. Put it in the macOS Keychain yourself:

```bash
security add-generic-password -s apple-mail-mcp -a you@example.com -w
```

For Gmail and iCloud this must be an **app-specific password**, not your login
password.

---

## Why it works this way

There is no supported Apple framework for reading a mailbox from outside Mail,
so the honest options are limited:

| Route | Supported | Fast | Notes |
| --- | --- | --- | --- |
| **AppleScript** | Yes — Mail's scripting dictionary | No | Bound by the Apple Event timeout. What this server uses by default. |
| **[MailKit](https://developer.apple.com/documentation/mailkit.md)** | Yes, but wrong tool | — | macOS 12+ *extension* API: content blocking, message actions, compose sessions, security. It hands your extension messages as they arrive; it cannot browse mailboxes or fetch stored mail. |
| **On-disk store** (`~/Library/Mail/V*/`, `Envelope Index`, `.emlx`) | No — undocumented | Yes | Needs Full Disk Access, and the format can change with any macOS release. |
| **IMAP** | Yes — a standard protocol | Yes | Independent of Mail. Needs credentials. The opt-in path above. |

Two rules keep the AppleScript backend from wedging Mail, both learned the hard
way:

* **No `whose` filters.** `messages whose id is N` walks the entire store and
  times out. The server iterates by index and filters in Python.
* **Never fetch bodies for a list.** Headers are cheap, bodies are not.
  `list_messages` returns headers only; bodies come from `read_messages` for the
  ids you actually want.

Every call takes a `scan` bound, so a request can't quietly turn into a
mailbox-wide walk.

---

## Troubleshooting

**"Mail got an error: AppleEvent timed out (-1712)"** — a request was too big, or
Mail is busy syncing. Lower `scan`, or use the IMAP path. If Mail itself has
become unresponsive, give it a minute; it recovers.

**"Operation not permitted"** — your client needs Automation permission for Mail
in System Settings → Privacy & Security → Automation.

**Empty results from an account that clearly has mail** — check the mailbox name
with `list_mailboxes`; it is `INBOX` on some accounts and `Inbox` on others.

---

## Development

```bash
git clone https://github.com/TrevorIkky/apple-mail-mcp
cd apple-mail-mcp
uv run apple-mail-mcp --selftest
```

## License

MIT
