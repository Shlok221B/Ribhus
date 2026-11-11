"""Level 1: HTTP page extraction (no browser)."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from ribhus.research.fetch_cache import CachedFetch, FetchCache
from ribhus.research.robots import shared_robots_cache
from ribhus.tools.web_extract import html_to_text

logger = logging.getLogger(__name__)

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

_USER_AGENT = (
    "Mozilla/5.0 (compatible; RibhusResearch/0.1; +https://github.com/ribhus)"
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
    redirect_chain: list[str] = field(default_factory=list)
    robots_allowed: bool = True
    from_cache: bool = False


class HostRateLimiter:
    """Simple per-host request spacing for polite crawling."""

    def __init__(self, min_interval: float = 0.35) -> None:
        self.min_interval = min_interval
        self._last: dict[str, float] = defaultdict(float)
        self._lock = asyncio.Lock()

    async def wait(self, host: str) -> None:
        if not host:
            return
        async with self._lock:
            now = time.monotonic()
            gap = now - self._last[host]
            if gap < self.min_interval:
                await asyncio.sleep(self.min_interval - gap)
            self._last[host] = time.monotonic()


_HOST_LIMITER = HostRateLimiter()
_DEFAULT_CACHE: FetchCache | None = None


def configure_fetch_cache(cache: FetchCache | None) -> None:
    global _DEFAULT_CACHE
    _DEFAULT_CACHE = cache


def get_fetch_cache() -> FetchCache | None:
    return _DEFAULT_CACHE


async def fetch_page(
    url: str,
    *,
    max_chars: int = 16_000,
    timeout: float = 30.0,
    retries: int = 2,
    respect_robots: bool = True,
    cache: FetchCache | None = None,
) -> PageSnapshot:
    cache = cache if cache is not None else _DEFAULT_CACHE
    robots_ok = await shared_robots_cache().allowed(url, enabled=respect_robots)
    if not robots_ok:
        return PageSnapshot(
            url=url,
            final_url=url,
            status_code=0,
            error="Blocked by robots.txt",
            thin=True,
            robots_allowed=False,
        )

    if cache is not None:
        hit = cache.get(url)
        if hit is not None:
            return _snapshot_from_cached(hit, max_chars=max_chars)

    host = host_of(url)
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    }

    last_error: str | None = None
    for attempt in range(max(1, retries + 1)):
        await _HOST_LIMITER.wait(host)
        try:
            async with httpx.AsyncClient(
                follow_redirects=True, timeout=timeout, headers=headers
            ) as client:
                response = await client.get(url)
            break
        except httpx.HTTPError as exc:
            last_error = str(exc)
            if attempt < retries:
                await asyncio.sleep(0.4 * (attempt + 1))
                continue
            return PageSnapshot(
                url=url,
                final_url=url,
                status_code=0,
                error=last_error,
                thin=True,
            )
    else:
        return PageSnapshot(
            url=url,
            final_url=url,
            status_code=0,
            error=last_error or "fetch failed",
            thin=True,
        )

    final = str(response.url)
    redirect_chain = _redirect_chain(response, url)
    content_type = (response.headers.get("content-type") or "").lower()
    body = response.text or ""

    if cache is not None and response.status_code < 500:
        cache.put(
            CachedFetch(
                url=url,
                final_url=final,
                status_code=response.status_code,
                content_type=content_type,
                body=body[:500_000],
                redirect_chain=redirect_chain,
                fetched_at=time.time(),
            )
        )

    if response.status_code >= 400:
        return PageSnapshot(
            url=url,
            final_url=final,
            status_code=response.status_code,
            error=f"HTTP {response.status_code}",
            thin=True,
            redirect_chain=redirect_chain,
        )

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
            redirect_chain=redirect_chain,
        )

    snap = parse_html(url, final, response.status_code, body, max_chars=max_chars)
    snap.redirect_chain = redirect_chain
    return snap


def _snapshot_from_cached(hit: CachedFetch, *, max_chars: int) -> PageSnapshot:
    if hit.status_code >= 400:
        return PageSnapshot(
            url=hit.url,
            final_url=hit.final_url,
            status_code=hit.status_code,
            error=f"HTTP {hit.status_code}",
            thin=True,
            redirect_chain=list(hit.redirect_chain),
            from_cache=True,
        )
    body = hit.body or ""
    content_type = (hit.content_type or "").lower()
    if "html" not in content_type and not body.lstrip().startswith(
        ("<!DOCTYPE", "<!doctype", "<html", "<HTML")
    ):
        text = body[:max_chars]
        return PageSnapshot(
            url=hit.url,
            final_url=hit.final_url,
            status_code=hit.status_code,
            text=text,
            thin=len(text.strip()) < 200,
            redirect_chain=list(hit.redirect_chain),
            from_cache=True,
        )
    snap = parse_html(
        hit.url, hit.final_url, hit.status_code, body, max_chars=max_chars
    )
    snap.redirect_chain = list(hit.redirect_chain)
    snap.from_cache = True
    return snap


def _redirect_chain(response: httpx.Response, original: str) -> list[str]:
    chain: list[str] = [original]
    try:
        for hop in response.history:
            chain.append(str(hop.url))
        final = str(response.url)
        if not chain or chain[-1] != final:
            chain.append(final)
    except Exception:  # noqa: BLE001
        pass
    # Deduplicate consecutive duplicates
    out: list[str] = []
    for item in chain:
        if not out or out[-1] != item:
            out.append(item)
    return out[:20]


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
