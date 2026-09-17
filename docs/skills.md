# Skill packaging

Ribhus skills are **directories**, not Python packages that get imported at runtime. The agent follows `skill.md`. Extra Python in `tools.py` is **not auto-run** — untrusted skills must not execute arbitrary code.

## Layout

```text
my-skill/
├── config.yaml     # required
├── skill.md        # required
├── README.md       # required
├── examples.md     # recommended
├── tools.py        # recommended (documentation only)
└── tests/
    └── test_skill.py
```

### config.yaml

```yaml
name: my-skill
version: 0.1.0
description: One-line what it does.
author: you
triggers:
  - phrase that should activate this skill
languages:
  - en
  - hi
permissions:
  - web
  - browser
```

`triggers` are case-insensitive substrings of the user prompt. Keep them specific enough that weather questions do not fire a travel skill.

### skill.md

Workflow, output format, and constraints. India skills should treat English, Hindi, and Hinglish as first-class, use ₹ and Indian dates where relevant, and refuse to invent filings, prices, or bookings.

### README.md

How to install, what the skill does, and a hero prompt.

## Commands

```bash
ribhus skill create my-skill
ribhus skill validate ./skills/my-skill
ribhus skill install ./skills/my-skill
ribhus skill install travel
ribhus skill list
ribhus skill remove my-skill
```

Install copies the directory into `.ribhus/skills/`. Bundled skills (`company-research`, `travel`) also live under `src/ribhus/skills/bundled/` and `skills/`.

## Bundled India skills

| Skill | Hero prompt |
|-------|-------------|
| `company-research` | Research this Indian company: Zoho |
| `travel` | Find me a hotel in Goa under ₹8,000 for Friday and Saturday. |

## Safety

- Skills are untrusted unless you reviewed them.
- Do not put secrets in a skill directory.
- Do not instruct the agent to log into accounts, bypass CAPTCHAs, or complete payments.
- `tools.py` is a note file in v0.1, not a plugin loader.
