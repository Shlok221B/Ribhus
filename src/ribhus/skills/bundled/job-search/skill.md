# Deep job search

## Goal
Specialized deep pass for hiring / openings. The agent’s general **depth decision** still applies to every research task; this skill only tightens the job-board workflow.

Find **real, current job openings** the user can apply to — not blog posts, not “how to get a job” articles, not empty aggregator spam. Fan out across boards, open listing pages, verify titles/companies/locations, and return concrete apply links.

## Languages
- Default: English
- If the user writes in Hindi or Hinglish, reply in the same style
- Keep company and role titles as published

## Constraints (non-negotiable)
- Do **not** invent openings. Every row needs a real URL you fetched or browsed.
- Do **not** stop after a single `web_search`. Shallow search is a failure mode.
- Prefer **direct apply / job detail URLs** (Greenhouse, Lever, Ashby, Workday, company `/careers`, LinkedIn job URLs) over SEO listicles.
- Do **not** log into LinkedIn/Indeed behind a wall. Use public pages only. If login blocks, skip that board and use another source.
- Do **not** auto-apply, upload a resume, or send email on the user’s behalf unless they explicitly ask later.
- If fewer than **5** solid openings survive verification, say so and keep searching (or ask one clarify).

## Phase 0 — Scope (fast)
Extract from the prompt: role/title keywords, seniority, location or remote, domain (AI/ML, backend, …), and any must-haves.
- If location **and** seniority are both missing, call `clarify` once with precise choices
  (e.g. Remote / Bengaluru / SF Bay / India-wide; Intern / Junior / Mid / Senior / Staff).
- Otherwise state brief assumptions and continue — do not stall.

Call `todo` with a short plan (merge=false), e.g.:
1. Fan-out search queries
2. Extract / browse top boards
3. Verify & shortlist openings
4. Write sourced answer

## Phase 1 — Fan-out search (required)
In **one tool turn when possible**, run **at least 4** distinct `web_search` calls (`max_results` 8–10 each). Vary queries; do not repeat the same string.

Query patterns (adapt to the role + location):
1. `{role} jobs {location}` (or `remote` if remote)
2. `{role} {location} site:greenhouse.io OR site:lever.co OR site:ashbyhq.com`
3. `{role} jobs site:linkedin.com/jobs`
4. `{role} {specialty} hiring {location}` (e.g. LLM, MLOps, RAG)
5. `{role} careers {known companies}` or `"{role}" "we're hiring" {location}`
6. Wellfound / YC / board-specific: `{role} site:wellfound.com` or `site:ycombinator.com/companies`

Also search India-relevant boards when location is India / remote-India:
`{role} site:naukri.com`, `{role} site:cutshort.io`, `{role} site:instahyre.com`.

## Phase 2 — Open the pages (required)
From search hits, pick **6–10** promising **job or careers URLs** (skip Medium/Reddit “how to” posts).

For each promising URL:
1. Prefer `web_extract` first.
2. If the extract is thin, blocked, JS shell, or missing job titles → use `browser`:
   - `open` the URL
   - `snapshot` (and `wait` if needed)
   - read job cards / title / company / location / apply link from the snapshot
   - optionally follow one job card into the detail page and snapshot again
3. For company career hubs, open 1–2 individual role pages so you have **direct apply URLs**.

Hard rule: if search snippets look good but you have not opened any listing page, you are not done — extract or browse before answering.

## Phase 3 — Verify & dedupe
Keep an opening only if you can fill:
- Role title
- Company
- Location / Remote
- Direct URL (job detail or apply page)
- One-line why it fits

Drop duplicates (same company + title). Prefer fresher / more specific pages.

Target **8–12** openings when available; minimum **5** before answering (or explain the shortfall after a real deep pass).

## Phase 4 — Answer format
Use this structure in the **final answer** (markdown):

```text
# Job search: <role> — <location / remote>

## Ask
- Role:
- Location / remote:
- Seniority:
- Assumptions:

## Openings
1. **<title>** — <company> — <location>
   Why: <one line fit>
   Apply: <url>
2. ...

## Also checked
- Boards / queries used (short list)
- Gaps: <what you could not verify>

## Next
Reply with a number to dig into that role (requirements, stack, similar openings), or refine location/seniority.
```

Mark todo items completed before the final answer.

## Failure modes to avoid
- Returning only “Top sites to search” or career-advice links
- Quoting search snippets without opening pages
- Fake companies or fabricated URLs
- Giving up after one empty search — change query shape and try boards + browser
