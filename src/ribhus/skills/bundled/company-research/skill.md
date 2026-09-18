# Company Research (India)

## Goal
Produce a clear, sourced brief about an Indian company or startup using **only legally accessible public information**.

## Languages
- Default: English
- If the user writes in Hindi or Hinglish, reply in the same style
- Keep legal entity names and CIN/GSTIN in their original form

## Workflow
1. Identify the company name (and location / industry if given).
2. `web_search` for official site, news, funding, founders.
3. Search for MCA / Ministry of Corporate Affairs public records, CIN, directors, registered address when available.
4. Prefer `web_extract` on promising public URLs; use `browser` or `http_request` if extract fails or the page needs JS.
5. Cross-check conflicting facts; prefer primary/public filings and reputable news.
6. Write the brief. **Cite URLs** for non-obvious claims.
7. Stop when the brief is complete — do not keep searching endlessly.

## Output format
Use this structure:

```text
# Company brief: <Name>

## Snapshot
- Legal / trade name:
- What they do (1–2 lines):
- HQ / geography:
- Founded / stage (if known):

## Public company details
- CIN / registration (if found):
- Directors / key people (if public):
- Registered address (if public):

## Product / market
- Offering:
- Customers / segment:
- Notable traction:

## Funding & news (if any)
- Funding / investors:
- Recent news:

## Sources
- <url>
- <url>
```

## Constraints
- Do **not** invent CIN, financials, or directors. If unknown, say "Not found in public sources."
- Do **not** give legal, tax, or investment advice.
- Do **not** scrape private/login-only data or bypass access controls.
- Prefer public MCA portals, company websites, and reputable news over random blogs.
- If multiple companies share a name, list candidates and ask which one — or pick the best match and state the assumption.
