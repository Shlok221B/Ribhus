"""Travel skill helpers: sticky selection / booking-handoff detection."""

from __future__ import annotations

import re

_SELECTION = re.compile(
    r"^\s*(?:option\s*)?([123]|one|two|three|first|second|third)\s*[.!?]?\s*$",
    re.IGNORECASE,
)

_HANDOFF = re.compile(
    r"\b("
    r"book(\s+it|\s+this|\s+that|\s+the)?"
    r"|finalize"
    r"|open\s+(the\s+)?(payment|booking|checkout)"
    r"|go\s+with"
    r"|take\s+(option\s*)?[123]"
    r"|choose\s+(option\s*)?[123]"
    r"|payment\s+page"
    r"|checkout"
    r")\b",
    re.IGNORECASE,
)

TRAVEL_HANDOFF_NUDGE = (
    "STOP. The user finalized a hotel from the shortlist. "
    "You MUST call the `browser` tool now: open the Source URL for that ONE option "
    "(from the shortlist in this conversation) in a single tab — do not open the "
    "other shortlist links. Then snapshot and click Book / Reserve / Continue toward "
    "the checkout or payment page. "
    "Do NOT say you cannot book. Do NOT only paste links. "
    "Leave the headed browser on the payment/checkout page for the user. "
    "Never enter card, UPI, OTP, CVV, or passwords."
)


def looks_travel_handoff(prompt: str) -> bool:
    """True when the user is picking a shortlist option or asking to open booking."""
    text = (prompt or "").strip()
    if not text:
        return False
    if _SELECTION.match(text):
        return True
    if _HANDOFF.search(text):
        return True
    # "2 please" / "number 1"
    if re.fullmatch(r"(?:number|no\.?|#)\s*[123]\s*", text, re.IGNORECASE):
        return True
    return False
