# Job search

Deep job-search skill for Ribhus. Bundled by default; also installable with:

```bash
ribhus skill install job-search
```

## What it does

Fan out across public job boards and career pages, open listing pages
(`web_extract` / `browser` when needed), and return verified openings with apply URLs.

General depth rules in the agent still apply to non-job research tasks.

Hero prompt:

> Find me AI engineer jobs remote

## Package layout

- `config.yaml` — name, version, triggers, permissions
- `skill.md` — workflow the agent must follow
- `examples.md` — sample prompts
- `tools.py` — notes only (not auto-imported)
- `tests/` — package checks
