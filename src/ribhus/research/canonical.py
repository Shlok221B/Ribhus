"""URL canonicalization and lead/record deduplication."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_TRACKING_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "fbclid",
        "gclid",
        "mc_cid",
        "mc_eid",
        "ref",
        "ref_src",
        "si",
        "source",
    }
)


def canonicalize_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
    except Exception:  # noqa: BLE001
        return raw.lower()
    scheme = (parsed.scheme or "https").lower()
    netloc = (parsed.netloc or "").lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    query_items = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS
    ]
    query_items.sort()
    query = urlencode(query_items)
    return urlunparse((scheme, netloc, path, "", query, ""))


def query_fingerprint(query: str) -> str:
    normalized = re.sub(r"\s+", " ", (query or "").strip().lower())
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


def record_fingerprint(company: str | None, role: str | None, url: str | None) -> str:
    company_n = re.sub(r"\s+", " ", (company or "").strip().lower())
    role_n = re.sub(r"\s+", " ", (role or "").strip().lower())
    if company_n and role_n:
        key = f"{company_n}|{role_n}"
    else:
        key = canonicalize_url(url or "")
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


_PORTAL_HOSTS = frozenset(
    {
        "linkedin.com",
        "indeed.com",
        "naukri.com",
        "glassdoor.com",
        "monster.com",
        "simplyhired.com",
        "ziprecruiter.com",
        "timesjobs.com",
        "shine.com",
    }
)

_ATS_HOST_HINTS = (
    "greenhouse.io",
    "lever.co",
    "ashbyhq.com",
    "myworkdayjobs.com",
    "workday.com",
    "wellfound.com",
)

_ATS_PATH_HINTS = ("/careers", "/jobs/", "/job/", "job-openings")


def lead_priority_score(url: str, title: str = "", snippet: str = "") -> float:
    """Higher = more worth inspecting (ATS/detail pages over portal homepages)."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = (parsed.path or "/").lower()
    score = 0.5
    text = f"{title} {snippet}".lower()
    if any(h in host for h in _ATS_HOST_HINTS):
        score += 0.35
    elif any(h in path for h in _ATS_PATH_HINTS) and "careers." in host:
        score += 0.3
    elif host.startswith("careers.") or host.startswith("jobs."):
        score += 0.25
    if any(host == p or host.endswith(f".{p}") for p in _PORTAL_HOSTS):
        # Prefer deep job URLs on portals over bare board roots
        deep = path.count("/") >= 3 and (
            "/jobs/" in path or "/job/" in path or path.rstrip("/").split("/")[-1].isdigit()
        )
        if deep:
            score += 0.1
        else:
            score -= 0.3
    if any(w in text for w in ("apply", "opening", "hiring", "job posting")):
        score += 0.1
    if any(w in text for w in ("how to get a job", "career advice", "resume tips")):
        score -= 0.4
    return max(0.0, min(1.0, score))
