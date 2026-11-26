# Ribhus — Open-Source AI Agent for India

> **Ribhus** is an open-source, self-hostable AI agent platform designed to understand, navigate, and act across the Indian digital ecosystem.
>
> **Vision:** Build an agent that doesn't just answer questions — it gets things done.

---

## 1. Executive Summary

Ribhus is an open-source autonomous AI agent inspired by the Vedic Ribhus — legendary craftsmen known for ingenuity, craftsmanship, and remarkable creations.

It combines LLM reasoning, tool calling, browser use, persistent memory, reusable skills, and multiple interfaces (CLI, Web, WhatsApp Web). The core stays model-provider agnostic and self-hostable.

**Who this roadmap is for:** a solo builder shipping a focused v0.1 — not a 15-phase enterprise platform plan.

### Positioning

**Primary**

> **Ribhus — Open-source AI agents for India.**

**Alternatives**

> **Ribhus — Agents that get things done.**

> **Ribhus — The open-source agent built for India.**

Do not use "India's first AI agent" as a factual claim unless independently verified. Own **India-first open-source agent ecosystem** instead.

### Solo v0.1 north star

A developer can self-host Ribhus, run it from the CLI, complete an **Indian company research** workflow via a skill, and use **WhatsApp Web** to draft a reply that only sends after explicit approval.

---

## 2. Product Philosophy

### 2.1 Action over conversation

Optimize for *"What can I do for you?"* rather than *"Here is some information."*

```text
User:
Find me a hotel in Goa under ₹8,000 for Friday and Saturday.

Traditional chatbot:
Here are some hotels...

Ribhus:
I searched available options, compared them, shortlisted three,
and prepared the options below.
```

### 2.2 User-owned agent

Users can self-host, choose their model provider, control data, inspect tool usage, revoke permissions, remove memories, and add/remove skills.

### 2.3 Open ecosystem

Core is open source. Skills are independently installable.

```bash
ribhus skill install company-research
ribhus skill install gst
ribhus skill install travel
```

### 2.4 Human approval for consequential actions

```text
READ          → often autonomous (search, browse, analyze)
WRITE         → configurable approval (message, email, create/modify)
HIGH IMPACT   → approval required (purchase, money, irreversible)
```

### 2.5 India first, not India only

India is the initial focus. Architecture stays globally extensible. Differentiation lives in **skills**, not hard-coded India into the agent core.

---

## 3. Core User Experience

```text
User → natural language → Ribhus
  → Plan → select tools/skills → Execute
  → Observe → Reason → (repeat) → Verify → Result
```

**Hero demo A — India company research**

> "Research this Indian startup and give me a company brief."

Ribhus should: find public company information, pull news and founder/funding context where available, synthesize a structured brief, and cite sources. Only use legally accessible public data.

**Hero demo B — WhatsApp with approval**

> "Open WhatsApp Web, find my conversation with Rahul, draft a reply based on the last message, and ask me before sending."

Ribhus should: locate the chat, read recent context, draft a reply, pause for approval, then send only after the user confirms.

---

## 4. High-Level Architecture

```text
                           USER
                             |
             +---------------+---------------+
             |               |               |
           CLI             Web          WhatsApp Web
             |               |               |
             +---------------+---------------+
                             |
                             v
                     CHANNEL GATEWAY
                             |
                             v
                    +----------------+
                    |  AGENT RUNTIME |
                    +----------------+
                             |
              +--------------+--------------+
              |              |              |
              v              v              v
           PLANNER        MEMORY          POLICY
              |              |              |
              +--------------+--------------+
                             |
                             v
                     TOOL / SKILL ROUTER
                             |
          +------------------+------------------+
          |                  |                  |
          v                  v                  v
       Browser           Terminal            APIs
                             |
                             v
                         OBSERVATION
                             |
                             v
                        LLM / MODEL
                             |
                             v
                     NEXT ACTION / DONE
```

The agent should not care which channel the request came from.

### Agent state machine

```text
START → PLANNING → EXECUTING
              |          |
           OBSERVE    ERROR
              |          |
           REASON    RECOVER
              |          |
         +----+----+-----+
         |         |
       DONE    NEED USER → PAUSED
```

---

## 5. Technology Stack (v0.1)

One recommended path — avoid mixing two ORM/web frameworks.

### Backend

- **Python**
- **FastAPI**
- **Pydantic**
- **SQLAlchemy** + **SQLite** (local) / **PostgreSQL** (optional production)
- **Redis** + a lightweight worker (only when background tasks arrive; not required for v0.1)
- **Docker** / Docker Compose

### AI

Provider-agnostic abstraction:

- OpenAI, Anthropic, Gemini, OpenRouter
- Ollama / vLLM / other OpenAI-compatible endpoints

### Browser

- Playwright + Chromium
- Browser profiles / session isolation
- Optional vision / computer-use model later

### Search

Pluggable search providers.

### Storage

- SQLite by default for solo local use
- PostgreSQL when self-hosting longer-lived deployments
- Object storage for files when needed
- Optional vector search for semantic memory (post–v0.1 polish)

### Observability

Structured logs, tool execution logs, task history, token/cost tracking.

---

## 6. Repository Structure

```text
ribhus/
|
├── apps/
│   ├── api/
│   ├── web/
│   └── cli/
|
├── core/
│   ├── agent/          # loop, planner, executor, state, policies
│   ├── memory/
│   ├── models/         # provider-agnostic LLM adapters
│   ├── tools/          # registry + browser, terminal, filesystem, web, http
│   └── skills/         # loader, registry, installer
|
├── channels/
│   ├── cli/
│   ├── web/
│   └── whatsapp_web/   # session, navigator, reader, sender, policy
|
├── skills/
│   ├── company-research/
│   ├── gst/
│   ├── travel/
│   ├── finance/
│   └── linkedin/
|
├── workers/            # later
├── database/
├── tests/
├── docs/
├── docker/
├── examples/
├── scripts/
├── pyproject.toml
└── README.md
```

---

## 7. Solo Phased Roadmap

Outcome-based. No day calendar. Ship each phase when the deliverable works.

### Phase 1 — Agent core + CLI

**Goal:** smallest useful autonomous agent.

- Receive prompt → call LLM → expose tools → execute → observe → continue → stop
- Model abstraction (multi-provider)
- Tool registry + initial tools: `web_search`, `http_request`, `read_file`, `write_file`, `python`, `terminal`
- CLI: `ribhus "…"` and interactive `ribhus`
- Basic tests

**Deliverable:** CLI agent that can search the web and reason over results.

### Phase 2 — Browser + permissions

**Goal:** operate websites safely.

- Playwright: open, click, type, scroll, read page, screenshot, extract content
- Domain allowlists, session isolation, credential isolation, rate limits, audit logs
- Risk levels on tools (`LOW` / `MEDIUM` / `HIGH` / `CRITICAL`)
- Approval gates for write / high-impact actions

**Deliverable:** *"Open this site, find pricing, summarize plans"* — with policy hooks ready for WhatsApp.

### Phase 3 — First India skill (company research)

**Goal:** prove India differentiation without hard-coding India into the core.

Primary v0.1 skill: **company research** (MCA / public corporate data + web/news where legally accessible).

- Skill format (`skill.md`, tools, examples, constraints, config)
- Skill loader + `ribhus skill install|list|remove|create`
- Second skill candidates after the first works: GST/invoice assistance (not authoritative tax advice), travel shortlist, Indian finance data

Languages: English, Hindi, Hinglish as first-class; other Indian languages later.

**Deliverable:** *"Research this Indian company"* → structured brief with sources.

### Phase 4 — WhatsApp Web channel

**Goal:** act through the user's existing WhatsApp Web session with hard safety rails.

```text
Ribhus → Browser Agent → WhatsApp Web → user's session
```

Flow: find chat → read context → draft → **approval** → type → send.

```text
channels/whatsapp_web/
  session.py | navigator.py | reader.py | sender.py | policy.py
```

**Critical constraints (non-negotiable):**

- This is **browser automation**, not the official WhatsApp Business API
- Subject to WhatsApp ToS and enforcement — **do not promise account safety**
- Configurable approval; no spam/bulk; rate limits; kill switch
- Isolate credentials/session data; user is responsible for their account
- Label the channel clearly in docs and UI

Approval UX may use the companion CLI/Web UI if WhatsApp itself cannot host a secure approve/edit/cancel flow.

**Deliverable:** draft reply to a named contact; send only after explicit approval.

### Phase 5 — Memory + skill packaging

**Goal:** remember useful context; make skills installable for others.

- Short-term (conversation / tool results / plan)
- Episodic (past tasks and outcomes)
- Semantic/user memory (preferences, workflows) with view / edit / delete / export / disable
- Skill packaging + docs so others can contribute India skills

**Deliverable:** memory survives sessions; a second India skill installs cleanly.

### Phase 6 — Public open-source launch

**Goal:** ship a repo others can run.

- License chosen deliberately (evaluate MIT / Apache-2.0 / AGPL-3.0 before launch)
- CONTRIBUTING, Code of Conduct, security policy
- Docker Compose: `git clone` → `docker compose up` → `ribhus`
- Docs: architecture, tools, skills, WhatsApp risks
- One India skill + one WhatsApp demo in README

**Deliverable:** public GitHub release of Ribhus v0.1.

### Later (not v0.1)

Keep the vision; do not block launch on these:

| Area | Examples |
|------|----------|
| More channels | Telegram, Discord, HTTP API, richer Web UI |
| Background tasks | schedulers, Redis workers, monitoring jobs |
| Computer use | OS-level mouse/keyboard beyond browser |
| Multi-agent | researcher / operator / coder — only after single-agent is reliable |
| Skill registry | `skills.ribhus.ai`, verification, sandbox for untrusted skills |
| Local-first polish | LOCAL / PRIVATE CLOUD / HYBRID disclosure modes |
| Enterprise | SSO, RBAC, team memory, admin, retention |
| Hosted product | Ribhus Cloud + Enterprise on top of OSS core |

---

## 8. MVP Definition (v0.1)

Success when a developer can:

```bash
git clone …
docker compose up
ribhus
```

And complete both:

1. **India:** *"Research this Indian company and give me a brief."* — skill + tools → sourced report  
2. **WhatsApp:** find chat → draft from last message → **ask before send** → controlled send  

### Definition of Done

- [ ] Open-source repository + clear license
- [ ] Docker setup
- [ ] CLI
- [ ] Agent loop + model abstraction + tool registry
- [ ] Web search + browser + terminal
- [ ] Permission / approval system
- [ ] Basic memory
- [ ] Skill format + at least one India skill (company research)
- [ ] WhatsApp Web channel (read, draft, approve, send)
- [ ] Basic observability + tests + documentation

**Do not wait for:** multi-agent, mobile app, many skills, perfect UI, every Indian integration, perfect local-model support, marketplace, enterprise, or hosted cloud.

---

## 9. Permissions & Security

### Permissions

Every tool declares permissions, risk level, and default approval.

```yaml
tool: whatsapp.send_message
risk: medium
permissions:
  - read_whatsapp
  - send_whatsapp
approval:
  default: required
```

Examples: web search `LOW` · read WhatsApp `MEDIUM` · send WhatsApp `MEDIUM` · delete file `HIGH` · purchase / money `CRITICAL`.

### Threats

Prompt injection, malicious sites/skills, credential theft, tool abuse, data exfiltration, destructive terminal use, browser session theft, supply-chain attacks.

### Mitigations

Sandbox, permission system, tool/domain allowlists, credential isolation, approval gates, audit logs, rate limits, timeouts, network restrictions, secret redaction.

Never give an unrestricted agent access to production infrastructure by default. Skills are untrusted unless verified.

---

## 10. Observability & Evaluation

Every task should produce a trace: goal, steps, tool calls, status, duration, tokens/cost.

### Eval categories

- **Basic:** search, read, APIs, tools  
- **Agentic:** recover from failure, choose tools, avoid wasted actions, verify results  
- **Safety:** ask before send, refuse unsafe actions, resist prompt injection, skills cannot access secrets  
- **India:** Hinglish, Indian date formats, ₹, GST terminology, Indian websites  
- **WhatsApp:** correct chat discovery, draft quality, approval never bypassed, kill switch works  

---

## 11. Developer Experience

```bash
ribhus skill create my-skill
ribhus skill install ./my-skill
```

```text
my-skill/
├── skill.md
├── tools.py
├── config.yaml
├── tests/
└── README.md
```

CLI surface:

```bash
ribhus
ribhus "Research this Indian company"
ribhus skill list|install|remove|create
ribhus memory list|delete <id>
```

### Web UI (minimal)

Prompt-first home ("What should I do?"), recent tasks, task detail (goal, status, tool calls, approvals, result, cost). Keep it deliberately simple for v0.1.

### WhatsApp UX

Natural chat for research/shortlists; for sends, always show draft + Approve / Edit / Cancel (companion UI if needed).

---

## 12. Branding

**RIBHUS** — Vedic craftsmen: ingenuity and craftsmanship.

Personality: intelligent, curious, technical, playful, capable, Indian — not overly traditional.

Avoid: stereotypical "India" visuals, excessive religious imagery, government-like branding, religious-product positioning.

Taglines: *Open-source AI agents for India.* · *Agents that get things done.* · *Build agents. Give them skills. Let them act.*

---

## 13. Launch & Community

### Build in public (progress beats, not a day calendar)

- Announcing an open-source agent for India  
- Agent can browse and use tools  
- First India skill (company research)  
- WhatsApp Web draft + approval prototype  
- Skills installable by others  

### Audience

Python / AI / automation developers, OSS contributors, Indian developer communities.

### Channels

GitHub, Product Hunt, Hacker News, Reddit, LinkedIn, X, Indian developer communities.

### Moat

Skills and integrations — GST, MCA/company research, travel, LinkedIn, GitHub, WhatsApp — with contributor recognition (and optional revenue share only if a hosted marketplace exists later).

### Monetization (later)

OSS first. Later: hosted cloud, premium compute/browser, enterprise controls, skill marketplace. Hosted WhatsApp/browser only where technically and legally appropriate.

---

## 14. Long-Term Vision

Not another chatbot — an **open agent operating layer**.

```text
                       RIBHUS
                          |
        +-----------------+-----------------+
        |                 |                 |
      THINK              ACT              REMEMBER
        |                 |                 |
       LLM              TOOLS             MEMORY
                          |
                     SKILL SYSTEM
                          |
          +---------------+---------------+
          |               |               |
       India          Developer        Global
       Skills          Skills          Skills
```

A mature install: a personal AI worker that understands context, uses applications, remembers workflows, and executes tasks — under user control. Core stays open source. Community builds skills. Users own deployments. India is where the ecosystem starts.

---

## 15. Guiding Principle

> **The Ribhus were makers.**
>
> **Ribhus should make things happen.**

**Build → Give it tools → Give it memory → Give it skills → Give it controlled access (including WhatsApp) → Let it act.**

That is the product.
