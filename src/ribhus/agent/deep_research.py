"""Decide when a prompt needs a deep research pass, and nudge if the agent stops early."""

from __future__ import annotations

import re

_DEEP_HINT_RE = re.compile(
    r"(?:"
    r"\bfind(?:\s+me)?(?:\s+a)?\b|"
    r"\bsearch(?:\s+for)?\b|"
    r"\blook(?:ing)?\s+(?:up|for)\b|"
    r"\bresearch\b|"
    r"\bcompare\b|"
    r"\bbest\b|"
    r"\balternatives?\b|"
    r"\bshortlist\b|"
    r"\bjobs?\b|"
    r"\bhiring\b|"
    r"\bopenings?\b|"
    r"\bwho\s+is\s+hiring\b|"
    r"\bwhat'?s\s+happening\b|"
    r"\bwhat\s+is\s+happening\b|"
    r"\bdig\s+deep\b|"
    r"\bthorough\b|"
    r"\bdeep\s+dive\b|"
    r"\blatest\b|"
    r"\bcurrent(?:ly)?\b|"
    r"\bnews\s+(?:about|on)\b|"
    r"\bvendors?\b|"
    r"\bsources?\s+for\b|"
    r"\bwho\s+(?:makes|sells|offers)\b"
    r")",
    re.IGNORECASE,
)

_SHALLOW_OVERRIDE_RE = re.compile(
    r"(?:"
    r"\bwhat\s+is\s+\d|"
    r"\bcalculate\b|"
    r"\bsummarize\s+(?:this|the\s+following)\b|"
    r"\brewrite\b|"
    r"\btranslate\b|"
    r"\bformat\b|"
    r"\bremember\b|"
    r"\bforget\b"
    r")",
    re.IGNORECASE,
)

DEEP_RESEARCH_NUDGE = (
    "Depth check: this ask needs a deep pass. Do not finish yet.\n"
    "1) Run at least 3 distinct `web_search` queries (different angles / site filters).\n"
    "2) `web_extract` several promising primary URLs — or `browser` open+snapshot "
    "when the page is JS-heavy or extract is thin.\n"
    "3) Then answer with verified items and cited URLs. "
    "Do not invent results or only list sites for the user to check."
)


def looks_deep_research(prompt: str) -> bool:
    text = (prompt or "").strip()
    if len(text) < 8:
        return False
    if _SHALLOW_OVERRIDE_RE.search(text) and not _DEEP_HINT_RE.search(text):
        return False
    return _DEEP_HINT_RE.search(text) is not None


def research_pass_is_shallow(tools_used: list[str]) -> bool:
    """True when the agent has not done a real multi-query + open-pages pass."""
    searches = sum(1 for name in tools_used if name == "web_search")
    deepened = any(
        name in {"web_extract", "browser", "http_request"} for name in tools_used
    )
    if searches < 3:
        return True
    if not deepened:
        return True
    return False
