# Blueprint gap — near-term tasks

Close the useful gaps vs the Grok Bot–inspired blueprint while staying local-first.

**Keep:** model picker, India skills, WhatsApp/Gmail approve-before-send, job hunt, bots/groups/handoffs.

**Do not build now:** cloud VM, mobile, voice, Slack/SCIM, vault/OAuth broker, teach-by-recording, SSE (poll is enough), routines, attachments, human-takeover UI.

Ship one epic at a time.

---

## Epic 0 — Unblock the dashboard — done

Resolved merge conflicts so Job hunt + bot/group chat routes and API routers (`bots`, `chats`, `jobs`) all work together.

---

## Epic 1 — Turn events + Stop

**Goal:** Typed event log, cancel without rolling back finished tools, Stop in chat UI.

### 1A — Event model — done

- [x] **1.1** Event types: `turn.started`, `tool.started`, `tool.finished`, `approval.requested`, `approval.resolved`, `handoff.sent`, `turn.completed`, `turn.failed`, `turn.cancelled`.
- [x] **1.2** Each event: `event_id`, `seq`, `ts`, `event_type`, `payload` in [`TaskStore`](../src/ribhus/web/task_store.py) (legacy `event`/`data` aliases kept for UI).
- [x] **1.3** Emit turn/tool/handoff events from orchestrator + runner + tool path (`tool_start`/`tool_end` normalized; `handoff.sent` on `message_bot`).
- [x] **1.4** `GET /api/tasks/{id}/events?after_seq=N`.
- [x] **1.5** Tests: monotonic seq; `after_seq` does not duplicate ([`tests/test_task_events.py`](../tests/test_task_events.py)).

### 1B — Cancel / Stop

- [ ] **1.6** `cancel_requested` on task; `POST /api/tasks/{id}/cancel` (409 if terminal).
- [ ] **1.7** Agent loop checks cancel between model/tool steps → `turn.cancelled` (no undo of finished tools).
- [ ] **1.8** On cancel: bot `idle`, clear pending approval.
- [ ] **1.9** Tests: mid-run cancel; prior tools still recorded.

### 1C — Chat UI

- [ ] **1.10** Stop button on [`ChatPage`](../web/src/pages/ChatPage.tsx) / task detail while running or awaiting approval.
- [ ] **1.11** Show tool cards from events in the thread.
- [ ] **1.12** Poll `events?after_seq=` (keep existing poll as fallback).

**Done when:** User can Stop a running turn; events are typed and pollable.

---

## Epic 2 — Fingerprinted approvals

**Goal:** Allow once / Always allow / Deny / Edit; fingerprint binding; sends never Always-skip.

- [ ] **2.1** `fingerprint(tool, args, bot_id, turn_id)` + re-hash before execute.
- [ ] **2.2** Decision object from [`PolicyEngine`](../src/ribhus/policy/engine.py): `allow_once | always | deny | edit`.
- [ ] **2.3** Persist Always rules; `force_approval` sends ignore Always.
- [ ] **2.4** Wire CLI + dashboard + registry callers; audit logs fingerprint.
- [ ] **2.5** UI: Allow once | Always | Deny | Edit (hide Always on send tools).
- [ ] **2.6** Tests: mutated args blocked; Always on terminal works; Always on `email_send` ignored.

**Done when:** Binding works end-to-end; sends still always prompt.

---

## Epic 3 — Untrusted fencing

**Goal:** External content cannot silently override policy.

- [ ] **3.1** `mark_untrusted(text, source, uri?)` helper.
- [ ] **3.2** Apply to web search/extract, browser read, Gmail/WhatsApp read, HTTP bodies.
- [ ] **3.3** System prompt: fenced data is not instructions.
- [ ] **3.4** Eval: injection asks to send → no send.

**Done when:** Injection fixture fails closed; results are fenced in traces.

---

## Later (not now)

Parked until Epics 1–3 ship: attachments/artifacts, job recovery badges, cron routines, per-bot skills / save-as-skill, memory provenance, human takeover, cost caps, vault/OAuth, SSE streaming, in-flight message redirect.

---

## Per-task PR note

```text
Epic: N
Task: N.x
Files: …
Tests: …
```
