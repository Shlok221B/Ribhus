"""Turn one link or one paste into several job openings."""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ribhus.jobs.errors import JobHuntError
from ribhus.jobs.extract import assert_public_job_url

BATCH_LIMIT = 10

FetchPage = Callable[[str], Awaitable[tuple[str, str, str, str]]]

_URL_RE = re.compile(r"https?://[^\s<>\"']+")
_ONE_NOTE = (
    "Prepared as one opening. If the text has several jobs, separate them with "
    "a line that contains only --- and prepare the batch again."
)
_ATS_HOSTS = (
    "greenhouse.io",
    "lever.co",
    "ashbyhq.com",
    "myworkdayjobs.com",
    "smartrecruiters.com",
)
_SKIP_PATH = ("/login", "/signin", "/privacy", "/cookie", "/wp-admin")


def public_urls(text: str) -> list[str]:
    found: list[str] = []
    for raw in _URL_RE.findall(text or ""):
        cleaned = raw.rstrip(".,);]")
        try:
            safe = assert_public_job_url(cleaned)
        except JobHuntError:
            continue
        if safe not in found:
            found.append(safe)
    return found


def split_marked_sections(text: str) -> list[dict[str, str]]:
    """Openings divided by a line that is only --- or ===."""
    parts = re.split(r"(?m)^[ \t]*(?:-{3,}|={3,})[ \t]*$", text or "")
    blocks = _blocks_from_parts(parts)
    return blocks if len(blocks) >= 2 else []


def blocks_around_urls(text: str) -> list[dict[str, str]]:
    """One block per URL when a paste contains several links and their descriptions."""
    urls = public_urls(text)
    if len(urls) < 2:
        return []
    positions: list[tuple[int, str]] = []
    cursor = 0
    source = text or ""
    for url in urls:
        pos = source.find(url, cursor)
        if pos < 0:
            continue
        positions.append((pos, url))
        cursor = pos + len(url)
    if len(positions) < 2:
        return []
    starts = [0]
    for index in range(1, len(positions)):
        prev_pos, prev_url = positions[index - 1]
        after = prev_pos + len(prev_url)
        gap = source[after : positions[index][0]]
        blank = re.search(r"\n\s*\n", gap)
        starts.append(after + blank.end() if blank else after)
    ends = [*starts[1:], len(source)]
    blocks: list[dict[str, str]] = []
    for start, end, (_pos, url) in zip(starts, ends, positions, strict=True):
        chunk = source[start:end].strip()
        title = url
        for line in chunk.splitlines():
            cleaned = line.strip()
            if cleaned and cleaned != url:
                title = cleaned[:180]
                break
        blocks.append({"url": url, "title": title, "text": chunk})
    return blocks


def listing_job_urls(html: str, page_url: str) -> list[str]:
    """Individual posting links on a careers or board page."""
    soup = BeautifulSoup(html or "", "html.parser")
    found: list[str] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        if not href or href.startswith(("#", "mailto:", "javascript:")):
            continue
        absolute = urljoin(page_url, href)
        try:
            absolute = assert_public_job_url(absolute.split("#", 1)[0])
        except JobHuntError:
            continue
        if not _is_posting_url(absolute, page_url):
            continue
        key = _url_key(absolute)
        if key in seen:
            continue
        seen.add(key)
        found.append(absolute)
    return found


def parse_model_openings(raw: str) -> list[dict[str, str]]:
    """Openings from a model JSON reply. Empty when the reply is not a real split."""
    cleaned = (raw or "").strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        return []
    try:
        payload = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return []
    rows = payload.get("openings") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    openings: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "").strip()
        role = " ".join(str(row.get("role") or "").split())
        company = " ".join(str(row.get("company") or "").split())
        email = str(row.get("email") or "").strip().lower()
        if len(text) < 80 or not (role or company):
            continue
        if email and email not in text.lower():
            email = ""
        title = f"{role} at {company}".strip() if role and company else role or company
        openings.append(
            {
                "url": "",
                "title": title[:180],
                "text": text,
                "email": email,
            }
        )
    return openings if len(openings) >= 2 else []


async def collect_openings(
    url: str,
    text: str,
    *,
    fetch: FetchPage,
    limit: int = BATCH_LIMIT,
) -> tuple[list[dict[str, str]], int, str]:
    pasted = (text or "").strip()
    link = (url or "").strip()
    notes: list[str] = []
    openings: list[dict[str, str]] = []
    omitted = 0

    sections = split_marked_sections(pasted) if pasted else []
    urls = public_urls(pasted) if pasted else []
    url_blocks = blocks_around_urls(pasted) if len(urls) >= 2 else []
    rich_blocks = (
        len(url_blocks) >= 2 and min(len(block["text"]) for block in url_blocks) >= 80
    )

    if len(sections) >= 2:
        openings = sections
    elif rich_blocks:
        openings = url_blocks
    elif len(urls) >= 2:
        openings, omitted, fetch_notes = await _fetch_all(urls, fetch, limit)
        notes.extend(fetch_notes)
    elif len(pasted) >= 80:
        openings = [_single_paste(pasted, link)]
        if len(pasted) > 500:
            notes.append(_ONE_NOTE)
    elif link:
        openings, link_notes, omitted = await _from_listing(link, fetch, limit)
        notes.extend(link_notes)
    else:
        raise JobHuntError(
            "Paste a public link, several job links, or descriptions separated by a line of ---."
        )

    if not openings:
        raise JobHuntError(
            "No openings found. Paste the descriptions, separated by a line of ---."
        )

    extra = max(0, len(openings) - limit)
    omitted += extra
    if extra:
        notes.append(f"Prepared the first {limit}. Left out {extra}.")
    elif omitted:
        notes.append(f"Prepared the first {limit}. Left out {omitted}.")
    return openings[:limit], omitted, " ".join(notes).strip()


def _single_paste(pasted: str, link: str) -> dict[str, str]:
    title = "Role"
    for line in pasted.splitlines():
        cleaned = " ".join(line.split())
        if len(cleaned) >= 4:
            title = cleaned[:180]
            break
    urls = public_urls(pasted)
    opening_url = urls[0] if len(urls) == 1 else ""
    if not opening_url and link.startswith(("http://", "https://")):
        opening_url = link
    return {"url": opening_url, "title": title, "text": pasted}


async def _from_listing(
    link: str,
    fetch: FetchPage,
    limit: int,
) -> tuple[list[dict[str, str]], list[str], int]:
    title, text, html, final = await fetch(link)
    page = final or link
    found = listing_job_urls(html, page)
    if len(found) >= 2:
        openings, omitted, notes = await _fetch_all(found, fetch, limit)
        if not openings:
            detail = notes[0] if notes else "Could not read the jobs linked from that page."
            raise JobHuntError(detail)
        return openings, notes, omitted
    if len(text.strip()) < 80:
        raise JobHuntError(
            "That page had almost no text. Paste the descriptions, separated by a line of ---."
        )
    return [{"url": link, "title": title or link, "text": text}], [], 0


async def _fetch_all(
    urls: list[str],
    fetch: FetchPage,
    limit: int,
) -> tuple[list[dict[str, str]], int, list[str]]:
    chosen = urls[:limit]
    omitted = max(0, len(urls) - len(chosen))
    openings: list[dict[str, str]] = []
    failed = 0
    for job_url in chosen:
        try:
            title, text, _html, final = await fetch(job_url)
        except JobHuntError:
            failed += 1
            continue
        if len(text.strip()) < 80:
            failed += 1
            continue
        openings.append(
            {
                "url": str(final or job_url),
                "title": title or job_url,
                "text": text,
            }
        )
    notes: list[str] = []
    if failed:
        notes.append(f"Skipped {failed} links that had no job text.")
    if not openings and chosen:
        raise JobHuntError(
            "Could not read those links. Paste the descriptions, separated by a line of ---."
        )
    return openings, omitted, notes


def _blocks_from_parts(parts: list[str]) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    for part in parts:
        chunk = part.strip()
        if len(chunk) < 80:
            continue
        title = "Role"
        for line in chunk.splitlines():
            cleaned = line.strip()
            if cleaned:
                title = cleaned[:180]
                break
        found = public_urls(chunk)
        blocks.append(
            {
                "url": found[0] if len(found) == 1 else "",
                "title": title,
                "text": chunk,
            }
        )
    return blocks


def _is_posting_url(url: str, page_url: str) -> bool:
    parsed = urlparse(url)
    page = urlparse(page_url)
    host = _host_key(parsed.hostname or "")
    page_host = _host_key(page.hostname or "")
    path = parsed.path.rstrip("/") or "/"
    page_path = page.path.rstrip("/") or "/"
    if host == page_host and path == page_path and (parsed.query or "") == (page.query or ""):
        return False
    lowered = path.lower()
    if lowered.endswith("/apply") or any(part in lowered for part in _SKIP_PATH):
        return False
    if re.search(r"\.(pdf|png|jpe?g|gif|svg|css|js|zip)$", lowered):
        return False
    ats = any(name in host for name in _ATS_HOSTS)
    same = host == page_host or host.endswith("." + page_host) or page_host.endswith("." + host)
    if not ats and not same:
        return False
    if ats and re.search(r"/jobs?/\d+|/[0-9a-f-]{8,}", path, re.IGNORECASE):
        return True
    if re.search(r"/(jobs?|careers?|positions?|openings?)/[^/]+", lowered):
        return path != page_path
    return False


def _host_key(host: str) -> str:
    return host.lower().removeprefix("www.").rstrip(".")


def _url_key(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    return f"{_host_key(parsed.hostname or '')}{path}?{parsed.query}"
