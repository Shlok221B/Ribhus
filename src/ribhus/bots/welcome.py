"""Draft the first message a newly created bot posts in its direct chat."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ribhus.config import Settings

log = logging.getLogger(__name__)

_WELCOME_SYSTEM = (
    "You write the first message a specialist AI bot posts when it is created. "
    "Speak in first person as the bot. Be warm, concrete, and short. "
    "No markdown headings, no emojis, no sales pitch. "
    "End with 2–4 clear next steps the human should reply with so you can start."
)


def template_welcome(*, name: str, job: str = "", label: str = "") -> str:
    """Deterministic welcome used when the model is unavailable."""
    bot = (name or "Bot").strip() or "Bot"
    role = (label or "").strip()
    brief = (job or "").strip()
    if brief and len(brief) > 280:
        brief = brief[:277].rstrip() + "…"

    intro = f"I'm set up as **{bot}**."
    if role and role.lower() != bot.lower():
        intro = f"I'm set up as **{bot}** ({role})."

    if brief:
        ownership = f"I'll own this: {brief}"
    else:
        ownership = (
            "Tell me what I should own — sources I can use, what success "
            "looks like, and anything I must never do without asking you."
        )

    steps = _suggested_steps(name=bot, job=brief, label=role)
    bullets = "\n".join(f"{i}. {step}" for i, step in enumerate(steps, 1))
    return f"{intro}\n\n{ownership}\n\nTo get started, reply with:\n{bullets}"


def _suggested_steps(*, name: str, job: str, label: str) -> list[str]:
    hay = f"{name} {label} {job}".lower()
    if any(
        k in hay
        for k in (
            "job",
            "career",
            "resume",
            "cv",
            "hiring",
            "recruit",
            "application",
            "linkedin",
        )
    ):
        return [
            "The roles or companies you want (titles, cities, remote/onsite)",
            "Your current resume / LinkedIn (paste or point me at a file)",
            "Whether I should draft applications only, or also send after you approve",
            "Any hard constraints (salary floor, notice period, no-go companies)",
        ]
    if any(k in hay for k in ("email", "gmail", "outreach", "cold mail")):
        return [
            "Who you want to reach (role, company, or a list)",
            "Your goal for the outreach (intro, partnership, follow-up…)",
            "Tone and anything I must never claim",
            "Whether drafts need your approval before every send (recommended)",
        ]
    if any(k in hay for k in ("whatsapp", "message", "chat")):
        return [
            "Who I should message (name as it appears in WhatsApp)",
            "What outcome you want from the conversation",
            "Any tone or language preferences",
            "Confirm sends always need your approval first",
        ]
    if any(k in hay for k in ("research", "company", "market", "competitor")):
        return [
            "The company / topic to research first",
            "What decision this research should unblock",
            "Preferred sources or regions (e.g. India-focused)",
            "How deep you want the first pass (quick brief vs deep dive)",
        ]
    if any(k in hay for k in ("travel", "hotel", "flight", "trip")):
        return [
            "Destination, dates, and budget",
            "Who is traveling and any must-haves",
            "Whether I should only research, or also book after approval",
        ]
    # Pull imperative-looking phrases from the job text as soft hints.
    hints = _extract_job_hints(job)
    if hints:
        return hints[:4]
    return [
        "The first concrete task you want me to take on",
        "Any files, links, or accounts I should use",
        "What I should ask you before doing (sends, deletes, spends…)",
        "How you'll know I'm doing a good job",
    ]


def _extract_job_hints(job: str) -> list[str]:
    if not job:
        return []
    parts = re.split(r"[\n.;]+", job)
    cleaned: list[str] = []
    for part in parts:
        text = part.strip().lstrip("-*• ").strip()
        if len(text) < 12 or len(text) > 120:
            continue
        cleaned.append(text[0].upper() + text[1:])
        if len(cleaned) >= 4:
            break
    if cleaned:
        return cleaned
    return []


async def draft_welcome(
    *,
    name: str,
    job: str = "",
    label: str = "",
    settings: Settings | None = None,
) -> str:
    """Draft a welcome via the model when possible; otherwise use the template."""
    fallback = template_welcome(name=name, job=job, label=label)
    if settings is None or not getattr(settings, "api_key", None):
        return fallback

    user = (
        f"Bot name: {name.strip()}\n"
        f"Label: {(label or '').strip() or '(none)'}\n"
        f"Job description:\n{(job or '').strip() or '(none — invent a sensible specialist role from the name)'}\n\n"
        "Write the first message now."
    )
    try:
        from ribhus.models.openai_compatible import OpenAICompatibleModel

        model = OpenAICompatibleModel(settings)
        response = await model.generate(
            [
                {"role": "system", "content": _WELCOME_SYSTEM},
                {"role": "user", "content": user},
            ],
            max_tokens=420,
        )
        text = (response.text or "").strip()
        if len(text) >= 40:
            return text
    except Exception as exc:  # noqa: BLE001 — never block bot creation
        log.info("welcome draft fell back to template: %s", exc)
    return fallback


async def seed_direct_welcome(
    *,
    chats: Any,
    bot: Any,
    settings: Settings | None = None,
) -> str | None:
    """Append a welcome to the bot's direct chat if it has no messages yet.

    Returns the drafted text when a message was posted, else None.
    """
    chat = chats.direct_for_bot(bot.id, bot_name=bot.name)
    if chat.messages:
        return None
    text = await draft_welcome(
        name=bot.name,
        job=getattr(bot, "job", "") or "",
        label=getattr(bot, "label", "") or "",
        settings=settings,
    )
    chats.append_message(
        chat.id,
        role="assistant",
        content=text,
        bot_id=bot.id,
        bot_name=bot.name,
    )
    return text
