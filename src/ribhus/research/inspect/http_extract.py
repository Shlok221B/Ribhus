"""Level 1: HTTP page extraction (no browser)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from ribhus.tools.web_extract import html_to_text

_CLOSED_RE = re.compile(
    r"(position\s+(has\s+been\s+)?(closed|filled)|"
    r"no\s+longer\s+accepting|"
    r"job\s+(is\s+)?(closed|unavailable|expired)|"
    r"this\s+job\s+is\s+no\s+longer|"
    r"application\s+(deadline|period)\s+(has\s+)?passed|"
    r"requisition\s+(closed|cancelled))",
    re.IGNORECASE,
)

_APPLY_HREF_RE = re.compile(
    r"(apply|application|careers?/apply|jobs?/.+/apply)",
    re.IGNORECASE,
)


@dataclass
class PageSnapshot:
    url: str
    final_url: str
    status_code: int
    title: str = ""
    text: str = ""
    meta: dict[str, str] = field(default_factory=dict)
    json_ld: list[dict[str, Any]] = field(default_factory=list)
    links: list[dict[str, str]] = field(default_factory=list)
    job_postings: list[dict[str, Any]] = field(default_factory=list)
    closed_match: str | None = None
    thin: bool = False
    error: str | None = None
    level: int = 1


async def fetch_page(
    url: str,
    *,
    max_chars: int = 16_000,
    timeout: float = 30.0,
) -> PageSnapshot:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; RibhusResearch/0.1; +https://github.com/ribhus)"
        ),
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    }
    try:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=timeout, headers=headers
        ) as client:
            response = await client.get(url)
    except httpx.HTTPError as exc:
        return PageSnapshot(
            url=url,
            final_url=url,
            status_code=0,
            error=str(exc),
            thin=True,
        )

    final = str(response.url)
    content_type = (response.headers.get("content-type") or "").lower()
    if response.status_code >= 400:
        return PageSnapshot(
            url=url,
            final_url=final,
            status_code=response.status_code,
            error=f"HTTP {response.status_code}",
            thin=True,
        )

    body = response.text or ""
    if "html" not in content_type and not body.lstrip().startswith(
        ("<!DOCTYPE", "<!doctype", "<html", "<HTML")
    ):
        text = body[:max_chars]
        return PageSnapshot(
            url=url,
            final_url=final,
            status_code=response.status_code,
            text=text,
            thin=len(text.strip()) < 200,
        )

    return parse_html(url, final, response.status_code, body, max_chars=max_chars)


def parse_html(
    url: str,
    final_url: str,
    status_code: int,
    html: str,
    *,
    max_chars: int = 16_000,
) -> PageSnapshot:
    title, text = html_to_text(html, max_chars=max_chars)
    soup = BeautifulSoup(html, "html.parser")
    meta: dict[str, str] = {}
    for tag in soup.find_all("meta"):
        key = tag.get("property") or tag.get("name")
        content = tag.get("content")
        if key and content:
            meta[str(key)] = str(content)[:500]

    json_ld: list[dict[str, Any]] = []
    job_postings: list[dict[str, Any]] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text() or ""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for node in _flatten_ld(data):
            json_ld.append(node)
            types = node.get("@type")
            type_list = types if isinstance(types, list) else [types]
            if any(str(t).lower() == "jobposting" for t in type_list if t):
                job_postings.append(node)

    links: list[dict[str, str]] = []
    for a in soup.find_all("a", href=True):
        href = str(a.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        abs_url = urljoin(final_url, href)
        label = " ".join(a.get_text(" ", strip=True).split())[:200]
        if _APPLY_HREF_RE.search(href) or _APPLY_HREF_RE.search(label):
            links.append({"url": abs_url, "text": label, "kind": "apply"})
        elif len(links) < 40:
            links.append({"url": abs_url, "text": label, "kind": "link"})

    closed = None
    match = _CLOSED_RE.search(text)
    if match:
        closed = match.group(0)

    thin = len(text.strip()) < 280 and not job_postings
    # JS shells often leave almost no main text
    if re.search(r"enable javascript|you need to enable|loading\.\.\.", text, re.I):
        thin = True

    return PageSnapshot(
        url=url,
        final_url=final_url,
        status_code=status_code,
        title=title,
        text=text,
        meta=meta,
        json_ld=json_ld[:20],
        links=links[:50],
        job_postings=job_postings,
        closed_match=closed,
        thin=thin,
        level=1,
    )


def _flatten_ld(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        out: list[dict[str, Any]] = []
        for item in data:
            out.extend(_flatten_ld(item))
        return out
    if isinstance(data, dict):
        if "@graph" in data and isinstance(data["@graph"], list):
            return _flatten_ld(data["@graph"])
        return [data]
    return []


def host_of(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:  # noqa: BLE001
        return ""
    return host[4:] if host.startswith("www.") else host
