"""Learn the user's global WhatsApp writing style from outgoing messages."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from ribhus.channels.whatsapp_web.register import _HINGLISH

WHATSAPP_STYLE_KEY = "whatsapp_style"

_STOP = frozenset(
    {
        "the",
        "a",
        "an",
        "to",
        "and",
        "or",
        "of",
        "in",
        "on",
        "for",
        "is",
        "it",
        "i",
        "me",
        "my",
        "you",
        "your",
        "we",
        "he",
        "she",
        "they",
        "this",
        "that",
        "with",
        "at",
        "be",
        "was",
        "are",
        "am",
        "do",
        "did",
        "not",
        "no",
        "yes",
        "ok",
        "okay",
    }
)

_EMOJI_RE = re.compile(
    "["
    "\U0001f300-\U0001f9ff"
    "\U00002600-\U000027bf"
    "\U0001f600-\U0001f64f"
    "]+",
    flags=re.UNICODE,
)
_WORD_RE = re.compile(r"[A-Za-z\u0900-\u097f']{2,}")


@dataclass
class IStyleSnapshot:
    """Heuristic snapshot of the user's outgoing WhatsApp voice."""

    register: str = "english"  # hinglish | english | hindi
    length_habit: str = "short"  # very_short | short | medium
    avg_chars: float = 0.0
    signature_phrases: list[str] = field(default_factory=list)
    emoji_rate: float = 0.0
    lowercase_heavy: bool = False
    exclaim_heavy: bool = False
    ellipsis_heavy: bool = False
    samples: list[str] = field(default_factory=list)
    message_count: int = 0


def _meta_looks_like_self(meta: str, self_names: list[str]) -> bool:
    """data-pre-plain-text often looks like '[10:42 pm, 1/1/2024] Shlok: '."""
    if not meta or not self_names:
        return False
    # Take the part after the last ']' (sender label) when present
    label = meta
    if "]" in meta:
        label = meta.rsplit("]", 1)[-1]
    label = label.strip().rstrip(":").strip().casefold()
    if not label:
        return False
    for name in self_names:
        n = str(name or "").strip().casefold()
        if not n or len(n) < 2:
            continue
        if n in label or label in n:
            return True
    return False


def _is_outgoing(msg: dict[str, Any], *, self_names: list[str] | None = None) -> bool:
    if msg.get("meta") == "raw-panel":
        return False
    if msg.get("direction") == "out" or msg.get("outgoing") is True:
        return True
    if self_names and _meta_looks_like_self(str(msg.get("meta") or ""), self_names):
        return True
    return False


def _outgoing_texts(
    messages: list[dict[str, Any]],
    *,
    self_names: list[str] | None = None,
) -> list[str]:
    out: list[str] = []
    for m in messages:
        if not _is_outgoing(m, self_names=self_names):
            continue
        text = str(m.get("text") or "").strip()
        if not text or text.startswith("[Ribhus]"):
            continue
        if len(text) > 400:
            text = text[:397] + "…"
        out.append(text)
    return out


def _detect_register(blob: str) -> str:
    compact = blob.casefold()
    has_devanagari = any("\u0900" <= ch <= "\u097f" for ch in blob)
    hinglish = any(marker in compact for marker in _HINGLISH)
    if has_devanagari and not hinglish:
        return "hindi"
    if hinglish:
        return "hinglish"
    if has_devanagari:
        return "hindi"
    return "english"


def _length_habit(avg: float) -> str:
    if avg < 25:
        return "very_short"
    if avg < 80:
        return "short"
    return "medium"


def _signature_phrases(texts: list[str], *, limit: int = 12) -> list[str]:
    counts: Counter[str] = Counter()
    for text in texts:
        low = text.casefold()
        for marker in _HINGLISH:
            if marker in low:
                counts[marker] += 2
        for word in _WORD_RE.findall(text):
            w = word.casefold()
            if w in _STOP or len(w) < 3:
                continue
            counts[w] += 1
    return [w for w, _ in counts.most_common(limit)]


def extract_outgoing_style(
    messages: list[dict[str, Any]],
    *,
    self_names: list[str] | None = None,
) -> IStyleSnapshot | None:
    """Build a style snapshot from outgoing WhatsApp bubbles only."""
    texts = _outgoing_texts(messages, self_names=self_names)
    if len(texts) < 1:
        return None

    blob = "\n".join(texts)
    lengths = [len(t) for t in texts]
    avg = sum(lengths) / len(lengths)
    emoji_hits = sum(1 for t in texts if _EMOJI_RE.search(t))
    lower_hits = sum(
        1
        for t in texts
        if any(c.isalpha() for c in t) and t == t.lower()
    )
    exclaim = sum(t.count("!") for t in texts)
    ellipsis = sum(t.count("...") + t.count("…") for t in texts)

    samples: list[str] = []
    seen: set[str] = set()
    for t in reversed(texts):
        key = t.casefold()[:80]
        if key in seen:
            continue
        seen.add(key)
        samples.append(t if len(t) <= 120 else t[:117] + "…")
        if len(samples) >= 6:
            break
    samples.reverse()

    return IStyleSnapshot(
        register=_detect_register(blob),
        length_habit=_length_habit(avg),
        avg_chars=round(avg, 1),
        signature_phrases=_signature_phrases(texts),
        emoji_rate=round(emoji_hits / len(texts), 2),
        lowercase_heavy=lower_hits / len(texts) >= 0.5,
        exclaim_heavy=exclaim / len(texts) >= 0.4,
        ellipsis_heavy=ellipsis / len(texts) >= 0.25,
        samples=samples,
        message_count=len(texts),
    )


def _parse_existing(existing: str) -> dict[str, Any]:
    """Best-effort parse of prior profile text into mergeable fields."""
    data: dict[str, Any] = {
        "phrases": [],
        "samples": [],
        "register": None,
        "length": None,
        "count": 0,
    }
    if not existing.strip():
        return data
    for line in existing.splitlines():
        low = line.strip()
        if low.lower().startswith("register:"):
            data["register"] = low.split(":", 1)[1].strip().lower()
        elif low.lower().startswith("length:"):
            data["length"] = low.split(":", 1)[1].strip().lower().replace(" ", "_")
        elif low.lower().startswith("signature words:"):
            raw = low.split(":", 1)[1]
            data["phrases"] = [p.strip() for p in raw.split(",") if p.strip()]
        elif low.lower().startswith("samples:"):
            continue
        elif low.startswith("- ") and "samples" in existing.lower():
            # Sample bullet under Samples section
            data["samples"].append(low[2:].strip())
        elif low.lower().startswith("from ~"):
            try:
                data["count"] = int(re.search(r"\d+", low).group())  # type: ignore[union-attr]
            except (AttributeError, ValueError):
                pass
    # Collect bullets after "Samples:"
    in_samples = False
    for line in existing.splitlines():
        if line.strip().lower().startswith("samples:"):
            in_samples = True
            continue
        if in_samples:
            if line.strip().startswith("- "):
                data["samples"].append(line.strip()[2:].strip())
            elif line.strip() and not line.strip().startswith("-"):
                in_samples = False
    # Dedupe samples preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for s in data["samples"]:
        k = s.casefold()
        if k in seen:
            continue
        seen.add(k)
        uniq.append(s)
    data["samples"] = uniq
    return data


def merge_style(existing_text: str | None, snapshot: IStyleSnapshot) -> str:
    """Merge a new snapshot into an existing profile blob (human-readable)."""
    prev = _parse_existing(existing_text or "")
    phrase_counts: Counter[str] = Counter()
    for p in prev.get("phrases") or []:
        phrase_counts[str(p).casefold()] += 1
    for p in snapshot.signature_phrases:
        phrase_counts[p.casefold()] += 2
    phrases = [w for w, _ in phrase_counts.most_common(14)]

    samples: list[str] = []
    seen: set[str] = set()
    for s in list(snapshot.samples) + list(prev.get("samples") or []):
        k = s.casefold()[:80]
        if k in seen:
            continue
        seen.add(k)
        samples.append(s)
        if len(samples) >= 6:
            break

    register = snapshot.register or prev.get("register") or "english"
    length = snapshot.length_habit or prev.get("length") or "short"
    total = int(prev.get("count") or 0) + snapshot.message_count

    cues: list[str] = []
    if snapshot.lowercase_heavy:
        cues.append("often lowercase")
    if snapshot.exclaim_heavy:
        cues.append("uses !")
    if snapshot.ellipsis_heavy:
        cues.append("uses …")
    if snapshot.emoji_rate >= 0.25:
        cues.append(f"emoji ~{int(snapshot.emoji_rate * 100)}% of msgs")
    if not cues:
        cues.append("plain punctuation")

    length_label = length.replace("_", " ")
    lines = [
        "WhatsApp writing style (you — global):",
        f"Register: {register}",
        f"Length: {length_label} (avg ~{snapshot.avg_chars:g} chars)",
        f"Signature words: {', '.join(phrases) if phrases else '(learning)'}",
        f"Tone cues: {', '.join(cues)}",
        f"From ~{total} outgoing messages observed",
        "Samples:",
    ]
    for s in samples:
        lines.append(f"- {s}")
    lines.append(
        "When drafting WhatsApp as the user: match this voice, word choice, "
        "and length. Do not sound more formal than these samples."
    )
    return "\n".join(lines)


def format_style_hint(profile_text: str | None) -> str:
    """Short injection for tool results / prompts."""
    text = (profile_text or "").strip()
    if not text:
        return ""
    # Keep hint compact for tool output
    lines = [ln for ln in text.splitlines() if ln.strip()][:10]
    body = "\n".join(lines)
    if len(body) > 700:
        body = body[:697] + "…"
    return "Your writing style (saved):\n" + body
