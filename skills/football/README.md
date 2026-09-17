# Football

Football club briefing skill for Ribhus. Install with:

```bash
ribhus skill install football
# or
ribhus skill install ./skills/football
```

## What it does

Asks once for your favourite club (if not in memory), remembers it with `memory_remember` (`key=football_club`), then briefs **live score if a match is on**, otherwise last result / next fixture (IST) / table from public sources. **No betting, tickets, or live streams.**

Hero prompt:

> What's happening with my football team?

## Package layout

- `config.yaml` — name, version, triggers, permissions
- `skill.md` — workflow the agent must follow
- `examples.md` — sample prompts
- `tools.py` — notes only (not auto-imported)
- `tests/` — package checks

See [docs/skills.md](../../docs/skills.md) for the contributor guide.
