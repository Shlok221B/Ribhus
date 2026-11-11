"""Choose which discovery leads are worth investigating."""

from __future__ import annotations

from urllib.parse import urlparse

from ribhus.research.models import SearchLead

_PORTAL_HOME_PATHS = frozenset(
    {"", "/", "/jobs", "/jobs/", "/careers", "/careers/", "/search", "/search/"}
)

_SKIP_HOST_FRAGMENTS = (
    "support.",
    "help.",
    "docs.",
    "status.",
    "blog.",
)


def is_inspect_worthy(lead: SearchLead) -> bool:
    url = (lead.canonical_url or lead.url or "").strip()
    if not url.startswith(("http://", "https://")):
        return False
    try:
        parsed = urlparse(url)
    except Exception:  # noqa: BLE001
        return False
    host = (parsed.hostname or "").lower()
    path = parsed.path or "/"
    if any(frag in host for frag in _SKIP_HOST_FRAGMENTS):
        return False
    text = f"{lead.title} {lead.snippet}".lower()
    if any(
        w in text
        for w in ("how to get a job", "career advice", "resume tips", "knowledge base")
    ):
        return False
    # Skip bare portal/board homes unless score is already high from ATS host
    if path.rstrip("/") in {p.rstrip("/") for p in _PORTAL_HOME_PATHS} or path in _PORTAL_HOME_PATHS:
        if lead.score < 0.7:
            return False
    return lead.score >= 0.35


def select_leads_for_inspect(
    leads: list[SearchLead],
    *,
    max_urls: int,
    already_seen: set[str] | None = None,
) -> list[SearchLead]:
    seen = set(already_seen or ())
    chosen: list[SearchLead] = []
    # Prefer higher score, then prefer ATS-looking hosts
    ordered = sorted(leads, key=lambda lead: lead.score, reverse=True)
    for lead in ordered:
        key = lead.canonical_url or lead.url
        if not key or key in seen:
            continue
        if not is_inspect_worthy(lead):
            continue
        seen.add(key)
        chosen.append(lead)
        if len(chosen) >= max_urls:
            break
    return chosen
