# Ribhus

<p align="center">
  <img src="web/public/ribhus-1.png" alt="The Ribhus, the divine craftsmen" width="560" />
</p>

<p align="center">
  Open-source AI agent for India. It searches, browses, remembers, and acts — and asks before it sends.
</p>

Ribhus runs on your machine. You pick the model. Skills add workflows such as Indian company research, travel shortlists, and football briefings. WhatsApp and Gmail drafts send only after you approve them.

## Features

- CLI and a local web dashboard
- Web search, page extract, browser, files, Python, and shell
- Approvals and an audit log for higher-risk actions
- Persistent memory you can list, edit, export, or turn off
- Installable skills: company research, travel, football
- WhatsApp Web and Gmail Web (browser automation, not official APIs)
- Nearby places and maps links
- MCP tools (`server__tool`), same approval path as built-in tools
- OpenAI, OpenRouter, or a local model such as Ollama

## Quick start

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/). Full setup, including Ollama: [docs/setup.md](docs/setup.md).

```bash
git clone https://github.com/Shlok221B/Ribhus.git
cd Ribhus
cp .env.example .env
# set RIBHUS_API_KEY (or point at Ollama — see docs/setup.md)

uv sync --extra dev
uv run playwright install chromium

uv run ribhus
```

One-shot examples:

```bash
uv run ribhus "Research this Indian company: Zoho"
uv run ribhus "Find me a hotel in Goa under ₹8,000 for Friday and Saturday."
uv run ribhus "What's happening with my football team?"
```

## Dashboard

```bash
uv sync --extra dashboard --extra dev
cd web && npm install && npm run build && cd ..
uv run ribhus dashboard
```

Opens http://127.0.0.1:8742/. Home, tasks, skills, memory, channels, MCP, and config. Frontend notes: [web/README.md](web/README.md).

Hot-reload the UI against a running API:

```bash
uv run ribhus dashboard --no-open   # terminal 1
cd web && npm run dev               # terminal 2 → http://127.0.0.1:5173
```

## Skills

```bash
uv run ribhus skill list
uv run ribhus skill install company-research
uv run ribhus skill install travel
uv run ribhus skill install football
uv run ribhus skill create my-skill
uv run ribhus skill validate ./skills/my-skill
uv run ribhus skill remove my-skill
```

Bundled skills live in `skills/` and `src/ribhus/skills/bundled/`. Install copies them into `.ribhus/skills/`. Format: [docs/skills.md](docs/skills.md).

## Memory

Stored in `.ribhus/memory.sqlite`: last turn, past tasks, and preferences (language, city, budget, football club). Relevant facts are pulled into the prompt. Older episodes are pruned (about 80 kept).

```bash
uv run ribhus memory list
uv run ribhus memory search "football"
uv run ribhus memory add "Prefer Hinglish replies" --key language
uv run ribhus memory forget football_club
uv run ribhus memory export --out memories.json
uv run ribhus memory disable
```

Set `RIBHUS_MEMORY_ENABLED=false` to turn memory off.

## WhatsApp Web

This drives WhatsApp Web in Chromium. It is not the WhatsApp Business API. It is subject to WhatsApp's Terms of Service. Ribhus does not promise account safety. You are responsible for your account.

```bash
uv run ribhus whatsapp status
uv run ribhus whatsapp status --check-login
uv run ribhus whatsapp listen
uv run ribhus whatsapp kill
uv run ribhus whatsapp resume

uv run ribhus "Find my WhatsApp chat with Rahul, draft a reply from the last message, and ask me before sending."
```

Flow: find the chat, read context, draft, then Approve / Edit / Cancel. Sends always need approval. `RIBHUS_AUTO_APPROVE` cannot skip them. One recipient per send. Rate limits and a cooldown apply. Session cookies stay in `.ribhus/whatsapp_profile/`. The generic browser tool cannot open WhatsApp Web.

`ribhus whatsapp listen` reads Note to Self. Reply `approve`, `cancel`, or `edit: …` there when a send is waiting.

First login: `RIBHUS_WHATSAPP_HEADED=true`, then scan the QR code in the Chromium window.

## Gmail Web

Same pattern: Chromium, a profile under `.ribhus/gmail_profile`, a kill switch, rate limits, and approve / edit / cancel on every send. This is not the Gmail API.

```bash
uv run ribhus email status --check-login
uv run ribhus "Check my inbox and draft a polite reply to the latest mail (do not send yet)"
uv run ribhus email kill
```

New mail uses `email_send`. A reply reads the thread first, then sends. The generic browser cannot open mail.google.com.

## Models

| Provider   | `RIBHUS_BASE_URL`                      | Notes                          |
|------------|----------------------------------------|--------------------------------|
| OpenAI     | `https://api.openai.com/v1`            | default                        |
| OpenRouter | `https://openrouter.ai/api/v1`         | use that provider's model id   |
| Ollama     | `http://localhost:11434/v1`            | `RIBHUS_API_KEY=ollama` is fine|

High-risk tools ask for approval unless `RIBHUS_AUTO_APPROVE=true`. WhatsApp and email sends still ask.

## MCP

```bash
uv run ribhus mcp init
uv run ribhus mcp list
uv run ribhus mcp test demo
```

Stdio servers show up as `server__tool` (for example `demo__add`). The GitHub server is off by default and needs Docker plus a personal access token. Do not commit the token.

```bash
export GITHUB_PERSONAL_ACCESS_TOKEN=ghp_…
uv run ribhus "List my open GitHub issues via MCP"
```

## Config

Copy `.env.example` to `.env`:

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

Product notes: [ribhus_product_roadmap.md](ribhus_product_roadmap.md).

## License

MIT
