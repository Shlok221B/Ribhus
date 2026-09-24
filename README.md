# Ribhus

Open-source AI agent for India. **Phase 5:** memory + installable skills.

## Quick start

Full walkthrough (uv install, PATH, OpenAI / Ollama Gemma 4, troubleshooting): **[docs/setup.md](docs/setup.md)**.

```bash
cp .env.example .env
# set RIBHUS_API_KEY (or Ollama — see docs/setup.md)

uv sync --extra dev
uv run playwright install chromium

uv run ribhus "Research this Indian company: Zoho"
uv run ribhus "Find me a hotel in Goa under ₹8,000 for Friday and Saturday."
uv run ribhus "What's happening with my football team?"
```

Interactive: `uv run ribhus`

### Skills

```bash
uv run ribhus skill list
uv run ribhus skill install travel
uv run ribhus skill install company-research
uv run ribhus skill install football
uv run ribhus skill create my-skill
uv run ribhus skill validate ./skills/my-skill
uv run ribhus skill remove my-skill
```

Bundled skills **company-research**, **travel**, and **football** load from `skills/` and `src/ribhus/skills/bundled/`. Install copies into `.ribhus/skills/`. Contributor format: [docs/skills.md](docs/skills.md).

### Memory

Memories persist in `.ribhus/memory.sqlite` (short-term last turn, episodic tasks, semantic preferences). Prefs like language / city / budget / football club are auto-extracted when you say them. Prompt injection pins those keys and FTS-searches what’s relevant to the current ask. Old episodes are pruned (keeps ~80).

```bash
uv run ribhus memory list
uv run ribhus memory search "football"
uv run ribhus memory show <id>
uv run ribhus memory add "Prefer Hinglish replies" --key language
uv run ribhus memory edit <id> --content "Prefer Hindi"
uv run ribhus memory forget football_club   # id or semantic key
uv run ribhus memory delete <id>
uv run ribhus memory export --out memories.json
uv run ribhus memory disable          # all recall/save off
uv run ribhus memory disable <id>     # one fact
uv run ribhus memory enable
```

Set `RIBHUS_MEMORY_ENABLED=false` to turn memory off from env.

### WhatsApp Web (browser automation)

This channel drives **WhatsApp Web in Chromium**. It is **not** the official WhatsApp Business API. It is subject to WhatsApp's Terms of Service and enforcement. **Ribhus does not promise account safety.** You are responsible for your account.

```bash
uv run ribhus whatsapp status
uv run ribhus whatsapp status --check-login   # open Chromium, scan QR if needed
uv run ribhus whatsapp listen  # Note to Self → Ribhus queries (reply on WA + CLI)
uv run ribhus whatsapp kill      # halt every WhatsApp action immediately
uv run ribhus whatsapp resume    # clears the kill switch; sends still need approval

uv run ribhus "Open WhatsApp Web, find my conversation with Rahul, draft a reply based on the last message, and ask me before sending."
```

After a WhatsApp task, the headed window stays open until you press Enter (so you can confirm the chat). Interactive `ribhus` reuses the same WhatsApp session until you `/exit`.

`ribhus whatsapp listen` opens **Message yourself / Note to Self**, treats each new message as a Ribhus query, prints the full answer in the terminal, and sends a short `[Ribhus]` reply back in that chat. When a send needs approval, the draft is posted to Note to Self — reply **approve**, **cancel**, or **edit: …** there (also mirrored in the terminal).

Flow: find chat → read context → draft → **Approve / Edit / Cancel in the CLI** → type → send.

Safety rails (non-negotiable):

- Sends **always** require explicit approval. `RIBHUS_AUTO_APPROVE=true` cannot skip them.
- One recipient per send. Bulk, broadcast, and copy-paste spam are blocked.
- Rate limits and a cooldown between sends.
- Isolated session cookies in `.ribhus/whatsapp_profile/` (treat like a password).
- The generic `browser` tool cannot open or control WhatsApp Web.
- Kill switch: `ribhus whatsapp kill` or `RIBHUS_WHATSAPP_ENABLED=false`.

First login: keep `RIBHUS_WHATSAPP_HEADED=true`, scan the QR code in the Chromium window with your phone.

### Providers

| Provider   | Example `RIBHUS_BASE_URL`              | Notes                          |
|------------|----------------------------------------|--------------------------------|
| OpenAI     | `https://api.openai.com/v1`            | default                        |
| OpenRouter | `https://openrouter.ai/api/v1`         | set model id accordingly       |
| Ollama     | `http://localhost:11434/v1`            | `RIBHUS_API_KEY=ollama` is fine|

High-risk tools ask for approval unless `RIBHUS_AUTO_APPROVE=true`. WhatsApp sends still ask.

## What's included

**Phase 1** — agent loop, CLI, search/http/files/python/terminal/process  
**Phase 2** — browser + risk levels + approvals + audit log  
**Phase 3** — skill format/loader/CLI + **company-research** (India)  
**Phase 4** — WhatsApp Web channel (read, draft, approve, send)  
**Phase 5** — persistent memory + skill packaging + **travel** / **football** skills  
**Also** — `web_extract`, `clarify`, `todo`, `edit_file`, `vision` / `screenshot_ask`, background `process`, **MCP client**, **Gmail Web** (browser automation)

### Email (Gmail Web)

Same transport pattern as WhatsApp: headed Chromium, persistent profile under `.ribhus/gmail_profile`, kill switch, rate limits, and approve/edit/cancel on every send. **Not** the Gmail API / IMAP.

```bash
# .env — no password; sign in once in the Chromium window
RIBHUS_EMAIL_ENABLED=true
RIBHUS_EMAIL_HEADED=true

uv run ribhus email status
uv run ribhus email status --check-login   # Google sign-in if needed
uv run ribhus "Check my inbox and draft a polite reply to the latest mail (do not send yet)"
uv run ribhus email kill                   # halt immediately
```

Flow: new outbound → `email_send` mode=new (approve/edit/cancel). Inbox reply → `email_reply` → `email_send` mode=reply. Generic `browser` / `web_extract` cannot open mail.google.com. After send, Chromium closes automatically.

### MCP (external tools)

```bash
uv run ribhus mcp init          # write .ribhus/mcp.json (demo + github)
uv run ribhus mcp list          # servers + tools
uv run ribhus mcp test demo     # call demo__add
```

Configured stdio servers appear as tools named `server__tool` (e.g. `demo__add`) and go through the same approval/audit path.

**GitHub MCP** (disabled by default in `mcp.json`): needs Docker + a PAT — never commit the token:

```bash
# set "enabled": true on the github entry in .ribhus/mcp.json
export GITHUB_PERSONAL_ACCESS_TOKEN=ghp_…
uv run ribhus mcp list          # should show github__… tools
uv run ribhus "List my open GitHub issues via MCP"
```

## Config (`.env`)

```bash
RIBHUS_API_KEY=
RIBHUS_MODEL=gpt-4o-mini
RIBHUS_AUTO_APPROVE=false
RIBHUS_APPROVE_AT=high
RIBHUS_BROWSER_HEADED=false
RIBHUS_WHATSAPP_ENABLED=true
RIBHUS_WHATSAPP_HEADED=true
RIBHUS_EMAIL_ENABLED=true
RIBHUS_EMAIL_HEADED=true
RIBHUS_MEMORY_ENABLED=true
```

## Development

```bash
uv run pytest
```

See [ribhus_product_roadmap.md](ribhus_product_roadmap.md). Next: Phase 6 — public open-source launch.

## License

MIT (tentative — finalize before public launch).
