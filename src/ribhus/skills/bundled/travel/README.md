# Travel

India travel shortlist + booking handoff skill for Ribhus. Install with:

```bash
ribhus skill install travel
# or
ribhus skill install ./skills/travel
```

## What it does

1. Shortlist hotels / stays in India from public sources (budget, dates, area).
2. When you **finalize** an option (`1` / `2` / `3` or the hotel name), open that stay’s
   **booking / payment page** in the browser and stop — **you** complete payment.
   Ribhus does not log in or enter card/UPI details.

Hero prompt:

> Find me a hotel in Goa under ₹8,000 for Friday and Saturday.

Then:

> 2

## Package layout

- `config.yaml` — name, version, triggers, permissions
- `skill.md` — workflow the agent must follow
- `examples.md` — sample prompts
- `tools.py` — notes only (not auto-imported)
- `tests/` — package checks

See [docs/skills.md](../../../../../docs/skills.md) for the contributor guide.
