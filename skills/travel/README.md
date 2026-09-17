# Travel

India travel shortlist skill for Ribhus. Install with:

```bash
ribhus skill install travel
# or
ribhus skill install ./skills/travel
```

## What it does

Shortlist hotels, stays, or weekend trips in India from public sources, with budget and dates. **Does not book or pay.**

Hero prompt:

> Find me a hotel in Goa under ₹8,000 for Friday and Saturday.

## Package layout

- `config.yaml` — name, version, triggers, permissions
- `skill.md` — workflow the agent must follow
- `examples.md` — sample prompts
- `tools.py` — notes only (not auto-imported)
- `tests/` — package checks

See [docs/skills.md](../../docs/skills.md) for the contributor guide.
