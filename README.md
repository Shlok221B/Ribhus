# Ribhus

Open-source AI agent for India. **Phase 4:** WhatsApp Web channel (draft → approve → send).

## Quick start

```bash
cp .env.example .env
# set RIBHUS_API_KEY

uv sync --extra dev
uv run playwright install chromium

uv run ribhus "Research this Indian company: Zoho"
```

Interactive: `uv run ribhus`

### Skills

```bash
uv run ribhus skill list
uv run ribhus skill install company-research
uv run ribhus skill create my-skill
uv run ribhus skill remove my-skill
```

Bundled skill **company-research** loads from `skills/` and `src/ribhus/skills/bundled/`. Install copies into `.ribhus/skills/`.

### WhatsApp Web (browser automation)

This channel drives **WhatsApp Web in Chromium**. It is **not** the official WhatsApp Business API. It is subject to WhatsApp's Terms of Service and enforcement. **Ribhus does not promise account safety.** You are responsible for your account.

```bash
uv run ribhus whatsapp status
uv run ribhus whatsapp kill      # halt every WhatsApp action immediately
uv run ribhus whatsapp resume    # clears the kill switch; sends still need approval

uv run ribhus "Open WhatsApp Web, find my conversation with Rahul, draft a reply based on the last message, and ask me before sending."
```

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

**Phase 1** — agent loop, CLI, search/http/files/python/terminal  
**Phase 2** — browser + risk levels + approvals + audit log  
**Phase 3** — skill format/loader/CLI + **company-research** (India)  
**Phase 4** — WhatsApp Web channel (read, draft, approve, send)

## Config (`.env`)

```bash
RIBHUS_API_KEY=
RIBHUS_MODEL=gpt-4o-mini
RIBHUS_AUTO_APPROVE=false
RIBHUS_APPROVE_AT=high
RIBHUS_BROWSER_HEADED=false
RIBHUS_WHATSAPP_ENABLED=true
RIBHUS_WHATSAPP_HEADED=true
```

## Development

```bash
uv run pytest
```

See [ribhus_product_roadmap.md](ribhus_product_roadmap.md). Next: Phase 5 — memory + skill packaging.

## License

MIT (tentative — finalize before public launch).
