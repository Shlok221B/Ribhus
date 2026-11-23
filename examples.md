# Ribhus task examples

Copy-paste prompts for the **Home** page / CLI. Each section notes what Ribhus does and which UX you should see.

> **Maintainers:** when you ship a user-facing feature, add or update a section here in the same change. See `.cursor/rules/maintain-examples.mdc`.

---

## Task titles

**Prompt**

```text
Find 15 Rishikesh hostels near Laxman Jhula with WhatsApp numbers for 24–25 Dec 2026 (1 night) and 30 Dec 2026–3 Jan 2027 (4 nights). Prefer dorms or private rooms for two guys. Include official phones where possible.
```

**What changed / what you’ll see**

- Tasks list shows a **short title** (≤30 characters), not the full prompt.
- Task detail heading uses that title; full text is under **Prompt**.

---

## Run progress — elapsed + 5s status line

**What you’ll see** (task detail / chat while a run is busy)

- Live elapsed clock like **`1m 49s`** next to the prompt / status.
- One-line status refreshes about every **5 seconds** from the latest tool/event (e.g. Searching…, Thinking · step 3), alternating with a short “still working” heartbeat so it never looks frozen.
- When the run finishes, elapsed freezes at the total time taken.

---

## Dashboard look — forge atmosphere

**What you’ll see**

- Low-opacity Ribhus craftsmen art behind Home, chat, and the main stage.
- Soft copper/gold ember wash; sidebar brand mark uses the forge plate.
- Favicon matches the copper bot mark / craftsmen crop.

---

## New bot — optional name / label

**What you’ll see**

- On **New bot**, Name and Label are optional.
- Empty name → server assigns the next free Vedic / Ribhus-circle name (Ribhu, Vibhvan, Vaja, Ashvins, Indra, Brihaspati, …).
- Empty label stays empty.
- Job / color / primary still work as before.

---

## WhatsApp — one contact (auto-send)

**Prompt**

```text
On WhatsApp, message Guptaji that I’ll reach by 7pm.
```

**What you’ll see**

- Uses Playwright WhatsApp Web (`whatsapp_reply` / `whatsapp_send`).
- **Approve / Edit / Cancel** before anything is typed into WhatsApp.
- No “draft buttons” clarify — ordinary 1:1 send stays automated.

---

## WhatsApp — many numbers (draft buttons, safer)

**Prompt**

```text
Here are 12 hostel WhatsApp numbers for Rishikesh. Draft one availability message I can send to each (I’ll send manually — don’t auto-send). Dates: 24–25 Dec 2026 and 30 Dec 2026–3 Jan 2027.
```

**What you’ll see**

- Final answer includes a `ribhus-whatsapp` block (or a markdown phone table).
- Task/chat result shows **WhatsApp drafts**: shared template + **WhatsApp** buttons.
- Click → system opens `wa.me` with text filled; **you** press Send.
- Mark **Opened** / **Sent** / **Skip** as you go.

---

## WhatsApp — ambiguous multi-send (clarify)

**Prompt**

```text
Message all of these hostels on WhatsApp asking for dorm availability for two guys on 24–25 Dec and 30 Dec–3 Jan. Numbers are in the table I’ll paste next.
```

**What you’ll see**

- Mid-task **Quick question** (clarify) with two choices:
  1. Draft buttons (safer for lists — you click Send in WhatsApp)
  2. Auto-send via WhatsApp Web (Playwright — slower, account risk)
- Choosing (1) → draft panel. Choosing (2) → one-by-one Playwright sends with approval each time.

---

## WhatsApp — explicit auto-send list

**Prompt**

```text
Auto-send via WhatsApp Web to each of these three numbers the same short intro (approve each send). Warn me about account risk once.
```

**What you’ll see**

- Playwright path; still **one recipient per** `whatsapp_send` + approval.
- No draft-button clarify (mode already stated).

---

## Nearby places / maps

**Prompt**

```text
Veg restaurants near FC Road Pune — show Maps links.
```

**What you’ll see**

- Uses live location / geocode; answer keeps Google Maps place links.
- Task detail may show a **Maps** strip when links are detected.

---

## Travel shortlist

**Prompt**

```text
Find me a hotel in North Goa under ₹8,000 for Friday and Saturday, two adults.
```

**What you’ll see**

- Travel skill / clarify for missing area or dates if needed.
- Shortlist with sources; booking handoff uses browser when you pick an option (you pay yourself).

---

## Company research

**Prompt**

```text
Research this Indian company: Zoho — funding, founders, recent news, cite sources.
```

**What you’ll see**

- Deep research pass (multiple searches + extracts), structured brief with URLs.

---

## Job search (skill)

**Prompt**

```text
Find active software engineer jobs in Bengaluru, 2–4 years experience, with working apply links.
```

**What you’ll see**

- Structured job cards when a `ribhus-jobs` fence is present (apply links, verification badges).

---

## Gmail send

**Prompt**

```text
Email alex@example.com subject “Ribhus demo” body “Hi — testing Gmail Web send from Ribhus.”
```

**What you’ll see**

- `email_send` with **Approve / Edit / Cancel** (not auto-approved).

---

## Memory

**Prompt**

```text
Remember that I prefer Hinglish for WhatsApp drafts.
```

**What you’ll see**

- Preference stored locally; later WhatsApp drafts can match that style.
- Manage via Memory page or `ribhus memory`.

---

## How to add a new example

1. Add a `##` section with a **Prompt** fenced block and **What you’ll see**.
2. Keep prompts realistic (India-first when relevant).
3. Call out dashboard UX (approvals, clarify, fences, buttons) when that’s the point of the feature.
4. Link related docs/skills only if they already exist — don’t invent paths.
