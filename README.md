# Ribhus

Open-source AI agent for India. **Phase 3:** skills + company research.

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

### Providers

| Provider   | Example `RIBHUS_BASE_URL`              | Notes                          |
|------------|----------------------------------------|--------------------------------|
| OpenAI     | `https://api.openai.com/v1`            | default                        |
| OpenRouter | `https://openrouter.ai/api/v1`         | set model id accordingly       |
| Ollama     | `http://localhost:11434/v1`            | `RIBHUS_API_KEY=ollama` is fine|

High-risk tools ask for approval unless `RIBHUS_AUTO_APPROVE=true`.

## What's included

**Phase 1** — agent loop, CLI, search/http/files/python/terminal  
**Phase 2** — browser + risk levels + approvals + audit log  
**Phase 3** — skill format/loader/CLI + **company-research** (India)

## Config (`.env`)

```bash
RIBHUS_API_KEY=
RIBHUS_MODEL=gpt-4o-mini
RIBHUS_AUTO_APPROVE=false
RIBHUS_APPROVE_AT=high
RIBHUS_BROWSER_HEADED=false
```

## Development

```bash
uv run pytest
```

See [ribhus_product_roadmap.md](ribhus_product_roadmap.md). Next: Phase 4 — WhatsApp Web.

## License

MIT (tentative — finalize before public launch).
