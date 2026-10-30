"""Pull a public job posting into role, company, emails, and keywords."""

from __future__ import annotations

import ipaddress
import re
from collections import Counter
from urllib.parse import urlparse

import httpx

from ribhus.jobs.errors import JobHuntError
from ribhus.tools.web_extract import html_to_text

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_SKIP_LOCAL = {
    "noreply",
    "no-reply",
    "donotreply",
    "do-not-reply",
    "notifications",
    "mailer-daemon",
    "privacy",
}
_SKIP_DOMAIN = {"example.com", "email.com", "sentry.io", "wixpress.com", "schema.org"}
_RECRUIT_HINTS = ("talent", "recruit", "hiring", "jobs", "career", "careers", "hr", "apply")
_SITE_TAILS = re.compile(
    r"\s+[|\-–—]\s+(Greenhouse|Lever|Ashby|Workday|LinkedIn|Indeed|Naukri|Jobs).*$",
    re.IGNORECASE,
)
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.#/-]{1,}")
_STOP = {
    "the", "and", "for", "with", "you", "your", "our", "are", "this", "that",
    "from", "will", "have", "has", "been", "into", "about", "their", "they",
    "them", "who", "what", "when", "where", "which", "while", "using", "use",
    "used", "able", "work", "working", "team", "role", "job", "join",
    "including", "include", "such", "other", "across", "within", "per", "via",
    "not", "but", "can", "may", "must", "should", "all", "any", "more", "than",
    "years", "year", "experience", "required", "requirements", "preferred",
    "qualification", "qualifications", "responsibilities", "responsibility",
    "skills", "skill", "ability", "strong", "excellent", "good", "plus", "etc",
    "we", "us", "of", "to", "in", "on", "at", "by", "as", "is", "be", "it",
    "its", "if", "or", "so", "do", "does", "did", "make", "help", "new", "well",
    "high", "looking", "candidate", "candidates", "position", "apply",
    "application", "company", "opportunity", "based", "full", "time", "part",
    "remote", "hybrid", "please", "click", "here", "description", "overview",
    "about", "our", "your", "with", "that", "this", "also", "both", "each",
    "over", "under", "between", "through", "during", "without", "within",
    "ability", "knowledge", "understanding", "environment", "responsibilities",
}


def assert_public_job_url(url: str) -> str:
    raw = (url or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise JobHuntError("Paste a public http(s) job link.")
    host = parsed.hostname.lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise JobHuntError("Paste a public job link, not a local address.")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
    ):
        raise JobHuntError("Paste a public job link, not a private address.")
    return raw


async def fetch_job_page(url: str) -> tuple[str, str]:
    safe = assert_public_job_url(url)
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=20.0,
            headers={"User-Agent": "Ribhus job hunt"},
        ) as client:
            response = await client.get(safe)
            response.raise_for_status()
    except JobHuntError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise JobHuntError(f"Could not fetch that job link: {exc}") from exc
    title, text = html_to_text(response.text, max_chars=20_000)
    if len(text.strip()) < 80:
        raise JobHuntError(
            "That page had almost no text. Paste the job description below "
            "instead of relying on a login wall such as LinkedIn or Naukri."
        )
    return title, text


_FIELD_LABELS = frozenset(
    {
        "location",
        "employment type",
        "department",
        "overview",
        "application",
        "compensation",
        "salary",
        "benefits",
        "about the role",
        "about us",
        "about the company",
        "requirements",
        "qualifications",
        "responsibilities",
        "what you'll do",
        "what you will do",
        "the role",
    }
)
_ROLE_WORDS = (
    "engineer",
    "developer",
    "manager",
    "designer",
    "analyst",
    "scientist",
    "intern",
    "lead",
    "architect",
)


def parse_posting(title: str, text: str) -> dict[str, str]:
    """Role, company, and department. Field labels such as Location are not a job title."""
    fields = _labeled_fields(text or "")
    company = _company_from_title(title or "") or _company_from_text(text or "") or "Company"
    role = _role_from_text(title or "", text or "")
    return {
        "role": role,
        "company": company,
        "department": fields.get("department", ""),
    }


def parse_role_company(title: str, text: str) -> tuple[str, str]:
    parsed = parse_posting(title, text)
    return parsed["role"] or "Role", parsed["company"]


def extract_emails(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for match in _EMAIL_RE.findall(text or ""):
        email = match.strip().strip(".").lower()
        local, _, domain = email.partition("@")
        if not local or not domain or "." not in domain:
            continue
        if local in _SKIP_LOCAL or domain in _SKIP_DOMAIN:
            continue
        if email in seen:
            continue
        seen.add(email)
        found.append(email)
    found.sort(key=lambda item: (-_recruit_score(item), item))
    return found


def extract_keywords(text: str, *, limit: int = 18) -> list[str]:
    focus = _focus_section(text or "")
    tokens = _TOKEN_RE.findall(focus)
    counts: Counter[str] = Counter()
    display: dict[str, str] = {}
    for token in tokens:
        key = token.lower().strip(".,;:")
        if key in _STOP or len(key) < 3 or key.isdigit():
            continue
        counts[key] += 2 if any(char in token for char in ".+#/") else 1
        if key[:1].isupper() or any(char.isupper() for char in token[1:]):
            counts[key] += 1
        display.setdefault(key, token if token[:1].isupper() else token)
    ranked = [display[key] for key, _score in counts.most_common(limit * 2)]
    unique: list[str] = []
    seen: set[str] = set()
    for word in ranked:
        marker = word.lower()
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(word)
        if len(unique) >= limit:
            break
    return unique


def company_slug(company: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (company or "").lower()).strip("_")
    return slug[:40] or "company"


def applicant_name(tex: str) -> str:
    patterns = (
        r"\\name\{([^{}]+)\}",
        r"\\textbf\{\s*\\Huge\s+([^{}]+)\}",
        r"\\bfseries\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})",
        r"^%\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\s+[—–-]",
        r"\\Huge\s*\{?([A-Z][A-Za-z .'-]{2,60})\}?",
    )
    for pattern in patterns:
        match = re.search(pattern, tex or "", re.MULTILINE)
        if match:
            name = " ".join(match.group(1).split())
            name = re.sub(r"\\[a-zA-Z]+", "", name).strip(" {}")
            if name:
                return name[:80]
    return ""


def resume_summary_sentence(tex: str) -> str:
    """First plain sentence from the resume body, for the application letter."""
    body = (tex or "").split(r"\begin{document}", 1)[-1]
    lines = [
        line.strip()
        for line in body.splitlines()
        if "\\" not in line and not line.strip().startswith("%") and len(line.strip()) >= 40
    ]
    text = " ".join(lines)
    sentence = re.split(r"(?<=[.])\s+", text, maxsplit=1)[0].strip()
    if len(sentence) < 40:
        return ""
    return sentence[:280]


def resume_portfolio_url(tex: str) -> str:
    """Personal site from the resume header. Skips LinkedIn and GitHub."""
    header = (tex or "").split(r"\begin{document}", 1)[-1]
    for marker in (r"\rsection", r"\section"):
        if marker in header:
            header = header.split(marker, 1)[0]
            break
    urls = re.findall(r"https?://[^\s}\\]+", header)
    for url in urls:
        cleaned = url.rstrip(".,)")
        lowered = cleaned.lower()
        if "linkedin.com" in lowered or "github.com" in lowered:
            continue
        return cleaned
    return ""


def resume_highlights(tex: str, limit: int = 8) -> list[str]:
    """Plain resume bullets, numbered ones first. No invented lines."""
    items: list[str] = []
    for match in re.finditer(r"\\item\s+(.+)", tex or ""):
        text = _plain_resume_line(match.group(1))
        if len(text) >= 40:
            items.append(text)
    numbered = [item for item in items if re.search(r"\d", item)]
    chosen = numbered or items
    return chosen[:limit]


def _plain_resume_line(raw: str) -> str:
    text = raw.split("\n", 1)[0]
    text = text.replace("--", "-").replace("~", " ")
    text = re.sub(r"\\(?:textbf|emph)\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\href\{[^{}]*\}\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?", "", text)
    text = text.replace("{", "").replace("}", "")
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text


def draft_email(
    *,
    name: str,
    role: str,
    company: str,
    summary: str = "",
    department: str = "",
    highlights: list[str] | None = None,
    portfolio: str = "",
    job_text: str = "",
) -> tuple[str, str]:
    """Cold email: short intro, real bullets, one ask. No keyword list."""
    who = name or "Applicant"
    place = company if company and company != "Company" else ""
    title = role if role and role not in {"Role", "Location"} else ""
    if title and place and title.lower() == (department or "").lower():
        title = ""
    subject = f"Could I help you build {place}?" if place else "Could I help you build this?"
    bullets = [_short_bullet(item) for item in (highlights or []) if item.strip()]
    if not bullets and summary.strip():
        bullets = [_short_bullet(summary)]
    bullets = bullets[:3]
    if len(bullets) > 2 and _cold_word_count("\n".join(bullets)) > 70:
        bullets = bullets[:2]
    observation = _company_observation(job_text, place)
    lines = [
        "Hi,",
        "",
        _intro_line(who, summary),
        "",
        *[f"- {bullet}" for bullet in bullets],
        "",
        "I can take a product from concept to production and stay on it after launch.",
        "",
        _intent_line(title, place, department),
    ]
    if observation:
        lines.extend(["", observation])
    if portfolio:
        lines.extend(["", portfolio])
    lines.extend(["", "Would you be open to a short conversation?", ""])
    if who != "Applicant":
        lines.append(who)
    body = "\n".join(lines).rstrip() + "\n"
    return subject[:180], body


def _intro_line(name: str, summary: str) -> str:
    clause = re.sub(r"\s+", " ", summary).strip()
    clause = re.split(r"(?<=[.])\s+", clause, maxsplit=1)[0].strip().rstrip(".")
    words = clause.split()
    clause = " ".join(words[:16]).rstrip(",;:")
    if not clause:
        return f"I'm {name}, and I build software and stay with it after launch."
    if re.match(r"^I\b", clause):
        return f"I'm {name}. {clause}."
    return f"I'm {name}, a {clause[0].lower()}{clause[1:]}."


def _intent_line(title: str, place: str, department: str) -> str:
    if title and place:
        target = f"a {title} role at {place}"
    elif department and place:
        target = f"an {department.lower()} role at {place}"
    elif place:
        target = f"a role at {place} where I can build and stay after launch"
    elif title:
        target = f"a {title} role"
    else:
        target = "a role where I can build and stay after launch"
    return f"I'm looking for {target}."


def _company_observation(job_text: str, company: str) -> str:
    if not job_text or not company:
        return ""
    flat = re.sub(r"\s+", " ", job_text).strip()
    match = re.search(re.escape(company), flat, re.IGNORECASE)
    if match is None:
        return ""
    window = re.split(r"[.!?]", flat[match.start() :], maxsplit=1)[0].strip()
    words = window.split()
    if not (6 <= len(words) <= 22):
        return ""
    if _is_label(window):
        return ""
    return window if window.endswith((".", "!", "?")) else f"{window}."


_DANGLING = {
    "and",
    "or",
    "but",
    "with",
    "by",
    "for",
    "to",
    "of",
    "the",
    "a",
    "an",
    "in",
    "on",
    "at",
}


def _short_bullet(text: str, max_words: int = 20) -> str:
    primary = re.sub(r"\s+", " ", text).strip(" .")
    if " by " in primary:
        left, right = primary.split(" by ", 1)
        if re.search(r"\d", left):
            left_words = left.split()
            right_words = right.split(" then ", 1)[0].split()[:12]
            while right_words and right_words[-1].lower().rstrip(",;:") in _DANGLING:
                right_words.pop()
            if len(left_words) <= 16 and right_words:
                primary = f"{left.strip(' .')} by {' '.join(right_words)}"
            else:
                primary = left.strip()
    words = [word for word in primary.split() if word]
    if not words:
        return ""
    if len(words) > max_words and any(re.search(r"\d", word) for word in words[:max_words]):
        words = words[:max_words]
    elif len(words) > max_words:
        number_at = [index for index, word in enumerate(words) if re.search(r"\d", word)]
        pivot = next(
            (
                index
                for index, word in enumerate(words)
                if word.lower().strip(",;:") in {"reached", "scored", "led", "shipped", "launched"}
            ),
            number_at[0] if number_at else 0,
        )
        end = min(len(words), (number_at[-1] if number_at else pivot) + 3)
        tail = words[pivot:end]
        head_end = min(6, len(words))
        for index, word in enumerate(words[:8]):
            if word.lower().strip(",;:") in {"simulation", "product", "platform", "marketplace"}:
                head_end = index + 1
                break
        head = words[:head_end]
        while head and head[-1].lower().rstrip(",;:") in _DANGLING:
            head.pop()
        if tail and tail[0].lower().strip(",;:") == "reached" and pivot >= len(head):
            words = [*head, "that", *tail]
        elif pivot > len(head):
            words = head + tail
        else:
            words = words[:max_words]
    while words and words[-1].lower().rstrip(",;:") in _DANGLING:
        words.pop()
    while words and words[0].lower().rstrip(",;:") in _DANGLING:
        words.pop(0)
    if not words:
        return ""
    sentence = " ".join(words).rstrip(",;:")
    if sentence[0].islower():
        sentence = sentence[0].upper() + sentence[1:]
    if not sentence.endswith("."):
        sentence += "."
    return sentence


def _cold_word_count(text: str) -> int:
    cleaned = re.sub(r"https?://\S+", " ", text or "")
    return len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'+-]*", cleaned))


def _recruit_score(email: str) -> int:
    local = email.split("@", 1)[0]
    return sum(2 for hint in _RECRUIT_HINTS if hint in local)


def _clip(value: str, fallback: str) -> str:
    text = re.sub(r"\s+", " ", value).strip(" |-–—")
    return text[:120] if text else fallback


def _is_label(value: str) -> bool:
    return value.strip().lower().rstrip(":") in _FIELD_LABELS


def _looks_like_role(value: str) -> bool:
    text = " ".join(value.split())
    if not text or len(text) > 70 or text.endswith("."):
        return False
    if _is_label(text):
        return False
    lowered = text.lower()
    return any(re.search(rf"\b{re.escape(word)}\b", lowered) for word in _ROLE_WORDS)


def _labeled_fields(text: str) -> dict[str, str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    fields: dict[str, str] = {}
    for index, line in enumerate(lines[:-1]):
        key = line.lower().rstrip(":")
        if key not in _FIELD_LABELS:
            continue
        nxt = lines[index + 1]
        if _is_label(nxt):
            continue
        fields.setdefault(key, nxt)
    if "department" in fields:
        fields["department"] = fields["department"]
    return fields


def _company_from_title(title: str) -> str:
    cleaned = re.sub(r"\s+", " ", title or "").strip()
    cleaned = _SITE_TAILS.sub("", cleaned).strip(" |-–—")
    match = re.search(r"\sat\s+(.+)$", cleaned, re.IGNORECASE)
    if match:
        return _clip(match.group(1).split("|")[0], "")
    parts = [part.strip() for part in re.split(r"\s+[|\-–—]\s+", cleaned) if part.strip()]
    if len(parts) >= 2:
        left, right = _assign_role_company(parts[0], parts[1])
        company = right if left == parts[0] else left
        if not _looks_like_role(company):
            return _clip(company, "")
    return ""


def _company_from_text(text: str) -> str:
    match = re.search(r"\bAt ([A-Z][A-Za-z0-9&]+),", text)
    if match:
        return match.group(1)
    match = re.search(r"\b([A-Z][A-Za-z0-9&]{2,})\s+is\s+(?:the|a|an)\b", text)
    if match and match.group(1).lower() not in {"this", "that", "there", "energy"}:
        return match.group(1)
    return ""


def _role_from_text(title: str, text: str) -> str:
    cleaned = re.sub(r"\s+", " ", title or "").strip()
    cleaned = _SITE_TAILS.sub("", cleaned).strip(" |-–—")
    match = re.search(r"(.+?)\s+at\s+(.+)$", cleaned, re.IGNORECASE)
    if match and _looks_like_role(match.group(1)):
        return _clip(match.group(1), "")
    parts = [part.strip() for part in re.split(r"\s+[|\-–—]\s+", cleaned) if part.strip()]
    if len(parts) >= 2:
        left, right = _assign_role_company(parts[0], parts[1])
        if _looks_like_role(left):
            return _clip(left, "")
        if _looks_like_role(right):
            return _clip(right, "")
    if _looks_like_role(cleaned):
        return _clip(cleaned, "")
    labeled = re.search(r"(?im)^(?:role|title|position)\s*[:\-]\s*(.+)$", text)
    if labeled and _looks_like_role(labeled.group(1)):
        return _clip(labeled.group(1), "")
    for line in text.splitlines():
        if _looks_like_role(line):
            return _clip(line, "")
    return ""


def _assign_role_company(left: str, right: str) -> tuple[str, str]:
    role_words = ("engineer", "developer", "manager", "designer", "analyst", "intern", "lead")
    left_role = any(word in left.lower() for word in role_words)
    right_role = any(word in right.lower() for word in role_words)
    if left_role and not right_role:
        return left, right
    if right_role and not left_role:
        return right, left
    return left, right


def _first_heading(text: str) -> str:
    for line in (text or "").splitlines():
        cleaned = line.strip()
        if 8 <= len(cleaned) <= 80:
            return cleaned
    return ""


def _focus_section(text: str) -> str:
    lowered = text.lower()
    markers = (
        "requirements",
        "qualifications",
        "what you'll",
        "what you will",
        "skills",
        "responsibilities",
    )
    indexes = [lowered.find(marker) for marker in markers if lowered.find(marker) >= 0]
    if not indexes:
        return text
    start = min(indexes)
    return text[start : start + 6000]
