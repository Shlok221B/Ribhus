"""Rewrite a LaTeX resume toward a posting without inventing facts."""

from __future__ import annotations

import re

from ribhus.jobs.errors import JobHuntError
from ribhus.models.openai_compatible import OpenAICompatibleModel

_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_SECTION_RE = re.compile(r"\\(?:section|subsection)\*?\{([^{}]+)\}")
_FENCE_RE = re.compile(r"^```(?:latex|tex)?\s*|\s*```$", re.IGNORECASE)

_SYSTEM = (
    "Rewrite this resume summary for one job. Return exactly 3 sentences of "
    "plain text and nothing else. Keep every tool, employer, and fact already "
    "in the summary. Do not add companies, degrees, metrics, or tools. "
    "Change emphasis and wording so the summary fits the posting."
)


def strip_latex_fence(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = _FENCE_RE.sub("", cleaned).strip()
    return cleaned


def assert_facts_preserved(original: str, tailored: str) -> None:
    if "\\documentclass" in original and "\\documentclass" not in tailored:
        raise JobHuntError("Tailored resume dropped the LaTeX document class.")
    if "\\begin{document}" in original and "\\begin{document}" not in tailored:
        raise JobHuntError("Tailored resume is not a complete document.")
    missing_years = sorted(set(_YEAR_RE.findall(original)) - set(_YEAR_RE.findall(tailored)))
    if missing_years:
        raise JobHuntError(f"Tailored resume dropped dates: {', '.join(missing_years)}.")
    original_emails = {item.lower() for item in _EMAIL_RE.findall(original)}
    tailored_emails = {item.lower() for item in _EMAIL_RE.findall(tailored)}
    missing_emails = sorted(original_emails - tailored_emails)
    if missing_emails:
        raise JobHuntError("Tailored resume dropped a contact email from the source.")
    for section in _SECTION_RE.findall(original):
        if section.lower() not in tailored.lower():
            raise JobHuntError(f"Tailored resume dropped the {section} section.")
    if original and not (0.55 * len(original) <= len(tailored) <= 1.8 * len(original)):
        raise JobHuntError("Tailored resume changed length too much to trust.")


async def tailor_resume(
    tex: str,
    *,
    role: str,
    company: str,
    keywords: list[str],
    job_text: str,
    model: OpenAICompatibleModel | None,
) -> tuple[str, str]:
    if model is None:
        return tex, "No model key set, so the PDF uses your base resume unchanged."
    span = _summary_span(tex)
    if span is None:
        return tex, "No summary paragraph to tailor. PDF uses your base resume."
    start, end = span
    lines = tex.splitlines()
    original_summary = " ".join(line.strip() for line in lines[start:end])
    user = (
        f"Role: {role}\nCompany: {company}\n\n"
        f"Job text:\n{job_text[:4000]}\n\n"
        f"Current summary:\n{original_summary}"
    )
    try:
        response = await model.generate(
            [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": user},
            ],
            max_tokens=220,
        )
    except Exception as exc:  # noqa: BLE001
        return tex, f"Tailor skipped ({_model_failure(exc)}). PDF uses your base resume."
    summary = _plain_summary(response.text or "")
    if not summary:
        return tex, "Tailor returned nothing. PDF uses your base resume."
    if not _summary_keeps_facts(original_summary, summary):
        return tex, "Tailor added facts that are not in the summary. PDF uses your base resume."
    lines[start:end] = [summary]
    tailored = "\n".join(lines)
    if not tailored.endswith("\n"):
        tailored += "\n"
    return tailored, "Summary rewritten for this posting. Employers, dates, and bullets were left as written."


def _summary_span(tex: str) -> tuple[int, int] | None:
    """Line range of the first plain summary paragraph after \\begin{document}."""
    lines = tex.splitlines()
    in_doc = False
    start: int | None = None
    for index, line in enumerate(lines):
        if r"\begin{document}" in line:
            in_doc = True
            continue
        if not in_doc:
            continue
        raw = line.strip()
        plain = bool(raw) and not raw.startswith("%") and "\\" not in raw and len(raw) >= 40
        if plain and start is None:
            start = index
            continue
        if start is not None and not plain:
            return start, index
    if start is not None:
        return start, len(lines)
    return None


def _plain_summary(text: str) -> str:
    cleaned = strip_latex_fence(text)
    cleaned = cleaned.replace("\n", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip('"')
    if "\\" in cleaned or len(cleaned) < 40:
        return ""
    return cleaned


def _summary_keeps_facts(original: str, rewritten: str) -> bool:
    original_years = set(_YEAR_RE.findall(original))
    if original_years - set(_YEAR_RE.findall(rewritten)):
        return False
    extra_years = set(_YEAR_RE.findall(rewritten)) - original_years
    if extra_years:
        return False
    if not (0.45 * len(original) <= len(rewritten) <= 1.8 * len(original)):
        return False
    return True


def _model_failure(exc: Exception) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    lowered = message.lower()
    if "connection" in lowered or "connect" in lowered or "11434" in lowered:
        return "Ollama is not running. Start it with `ollama serve`, then prepare again"
    return message


_EMAIL_SYSTEM = (
    "You write cold job emails. Return JSON only, with keys subject and body. "
    "No markdown fences.\n"
    "Length: 80-120 words. Never exceed 150.\n"
    "Subject: creative, curiosity-driven, and personalized. "
    'A good shape is "Could I help you build [Company]?"\n'
    "Introduction: one short sentence about who the candidate is.\n"
    "Achievements: 2 or 3 concise bullet points, each starting with \"- \". "
    "Use only measurable facts from the allowed resume lines, and keep the wording close to those lines. "
    "Do not invent employers, products, titles, metrics, tools, causes, or regulations. "
    "Do not upgrade a verb into a bigger claim.\n"
    "Value proposition: one short sentence grounded in the resume summary. "
    "Do not claim a new technology or a result at this company.\n"
    "Intent: one short sentence on the kind of role they want.\n"
    "Personalization: one sentence about the company that is already in the job text. "
    "Make it about the company, not a restatement of the requirements. "
    "If the job text does not support one, omit it.\n"
    "Portfolio: include the given portfolio URL once, on its own line. "
    "If none is given, do not invent a link.\n"
    "CTA: end with one simple question inviting a conversation, then the candidate's name.\n"
    "Tone: human, confident, conversational, and direct. Short sentences. Plain English. "
    "No corporate jargon, fluff, generic AI language, or keyword lists."
)


async def write_application_email(
    *,
    model: OpenAICompatibleModel | None,
    name: str,
    role: str,
    company: str,
    department: str,
    summary: str,
    job_text: str,
    fallback: tuple[str, str],
    highlights: list[str] | None = None,
    portfolio: str = "",
) -> tuple[str, str]:
    """Ask the model for a cold email. Keep the template if it fails the rules."""
    if model is None:
        return fallback
    who = name or "Applicant"
    facts = "\n".join(f"- {line}" for line in (highlights or []) if line.strip())
    user = (
        f"Applicant: {who}\n"
        f"Role: {role or '(unknown)'}\n"
        f"Company: {company or '(unknown)'}\n"
        f"Department: {department or '(unknown)'}\n"
        f"Portfolio: {portfolio or '(none)'}\n"
        f"Resume sentence: {summary or '(none)'}\n\n"
        f"Allowed resume facts:\n{facts or '(none)'}\n\n"
        f"Job text:\n{job_text[:6000]}"
    )
    try:
        response = await model.generate(
            [
                {"role": "system", "content": _EMAIL_SYSTEM},
                {"role": "user", "content": user},
            ],
            max_tokens=550,
        )
    except Exception:  # noqa: BLE001
        return fallback
    parsed = _email_json(response.text or "")
    if parsed is None:
        return fallback
    subject, body = parsed
    allowed = "\n".join([summary or "", facts, portfolio or ""])
    if not _email_is_cold(subject, body, who, company=company, portfolio=portfolio, allowed=allowed):
        return fallback
    return subject[:180], body


def _email_json(text: str) -> tuple[str, str] | None:
    import json

    cleaned = strip_latex_fence(text).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        payload = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    subject = str(payload.get("subject") or "").strip()
    body = str(payload.get("body") or "").strip()
    if not subject or not body:
        return None
    if not body.endswith("\n"):
        body += "\n"
    return subject, body


def _email_is_cold(
    subject: str,
    body: str,
    name: str,
    *,
    company: str,
    portfolio: str,
    allowed: str,
) -> bool:
    cleaned_subject = re.sub(r"\s+", " ", subject).strip()
    if not cleaned_subject or len(cleaned_subject) > 90:
        return False
    if cleaned_subject.lower() in {"location", "role", "company"}:
        return False
    place = company if company and company != "Company" else ""
    if place and place.lower() not in cleaned_subject.lower() and place.lower() not in body.lower():
        return False
    lowered = body.lower()
    if name and name.lower() not in lowered:
        return False
    if "emphasizes" in lowered or "keyword" in lowered:
        return False
    bullets = [
        line
        for line in body.splitlines()
        if line.strip().startswith(("- ", "* ", "• "))
    ]
    if not 2 <= len(bullets) <= 3:
        return False
    trailing = [line.strip() for line in body.splitlines() if line.strip()]
    if not trailing or "?" not in "\n".join(trailing[-2:]):
        return False
    if portfolio and portfolio not in body:
        return False
    words = _email_words(body)
    if not 60 <= words <= 150:
        return False
    allowed_numbers = _numbers(allowed)
    if _numbers(body) - allowed_numbers:
        return False
    return True


def _email_words(text: str) -> int:
    cleaned = re.sub(r"https?://\S+", " ", text or "")
    return len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'+-]*", cleaned))


def _numbers(text: str) -> set[str]:
    return {raw.replace(",", "") for raw in re.findall(r"\d[\d,]*", text or "")}
