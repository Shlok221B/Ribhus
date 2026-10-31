"""Orchestrate fetch → tailor → PDF → draft. Send is a separate approved step."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ribhus.channels.gmail_web.policy import EmailPolicy, EmailPolicyError
from ribhus.channels.gmail_web.sender import GmailSender
from ribhus.channels.gmail_web.session import GmailSession
from ribhus.config import Settings, get_settings
from ribhus.jobs.compile import compile_resume, tectonic_available
from ribhus.jobs.errors import JobHuntError
from ribhus.jobs.extract import (
    applicant_name,
    company_slug,
    draft_email,
    extract_emails,
    extract_keywords,
    fetch_job_page,
    parse_posting,
    resume_highlights,
    resume_portfolio_url,
    resume_summary_sentence,
)
from ribhus.jobs.store import JobStore
from ribhus.jobs.tailor import tailor_resume, write_application_email
from ribhus.models.openai_compatible import OpenAICompatibleModel


class JobHuntService:
    def __init__(self, root: Path) -> None:
        self.store = JobStore(root)

    def status(self, settings: Settings | None = None) -> dict[str, Any]:
        settings = settings or get_settings()
        policy = _email_policy(settings)
        email = policy.status()
        return {
            "resume_saved": self.store.resume_saved(),
            "resume_path": str(self.store.resume_path),
            "tectonic": tectonic_available(),
            "model_ready": bool(settings.api_key),
            "email_enabled": bool(email.get("enabled")),
            "email_killed": bool(email.get("killed")),
            "email_profile": str(settings.ribhus_dir / "gmail_profile"),
            "applications": self.store.list_applications(),
        }

    def save_resume(self, tex: str) -> dict[str, Any]:
        return self.store.save_resume(tex)

    async def prepare(
        self,
        url: str = "",
        text: str = "",
        settings: Settings | None = None,
    ) -> dict[str, Any]:
        settings = settings or get_settings()
        source = self.store.read_resume()
        pasted = (text or "").strip()
        link = (url or "").strip()
        if len(pasted) >= 80:
            title, body_text = _title_from_paste(pasted), pasted
        elif link:
            title, body_text = await fetch_job_page(link)
        else:
            raise JobHuntError(
                "Paste a job link, or paste the job description (a few sentences)."
            )
        text = body_text
        posting = parse_posting(title, text)
        role = posting["role"]
        company = posting["company"]
        department = posting["department"]
        emails = extract_emails(text)
        keywords = extract_keywords(text)
        name = applicant_name(source)
        summary = resume_summary_sentence(source)
        highlights = resume_highlights(source)
        portfolio = resume_portfolio_url(source)
        model = _model(settings)
        tailored, note = await tailor_resume(
            source,
            role=role or department or "the role",
            company=company,
            keywords=keywords,
            job_text=text,
            model=model,
        )
        fallback = draft_email(
            name=name,
            role=role,
            company=company,
            summary=summary,
            department=department,
            highlights=highlights,
            portfolio=portfolio,
            job_text=text,
        )
        subject, body = await write_application_email(
            model=model,
            name=name,
            role=role,
            company=company,
            department=department,
            summary=summary,
            job_text=text,
            fallback=fallback,
            highlights=highlights,
            portfolio=portfolio,
        )
        if not role:
            role = department or "Role"
        slug = company_slug(company)
        pdf_file = f"resume_{slug}.pdf"
        record = self.store.create(
            {
                "url": link if link.startswith(("http://", "https://")) else "",
                "title": title,
                "company": company,
                "role": role,
                "emails": emails,
                "keywords": keywords,
                "excerpt": text[:1800],
                "to": emails[0] if emails else "",
                "subject": subject,
                "body": body,
                "pdf_file": pdf_file,
                "pdf_ready": False,
                "tailor_note": note,
                "status": "failed",
                "error": "",
            }
        )
        tex_path = self.store.write_tex(record["id"], tailored if tailored.endswith("\n") else tailored + "\n")
        try:
            compile_resume(tex_path, self.store.folder(record["id"]) / pdf_file)
        except JobHuntError as exc:
            tex_path.write_text(source if source.endswith("\n") else source + "\n", encoding="utf-8")
            try:
                compile_resume(tex_path, self.store.folder(record["id"]) / pdf_file)
            except JobHuntError as compile_exc:
                return self.store.update(
                    record["id"],
                    status="failed",
                    error=str(compile_exc),
                    pdf_ready=False,
                )
            return self.store.update(
                record["id"],
                status="ready",
                error="",
                pdf_ready=True,
                tailor_note=f"{note} The rewrite did not compile ({exc}). PDF is your base resume.",
            )
        return self.store.update(
            record["id"],
            status="ready",
            error="",
            pdf_ready=True,
        )

    def pdf_file(self, application_id: str) -> Path:
        return self.store.pdf_path(self.store.get(application_id))

    async def send(
        self,
        application_id: str,
        *,
        to: str,
        subject: str,
        body: str,
        session: GmailSession,
        policy: EmailPolicy,
    ) -> dict[str, Any]:
        record = self.store.get(application_id)
        if record.get("status") == "sent":
            raise JobHuntError("This application was already sent.")
        if not record.get("pdf_ready"):
            raise JobHuntError(record.get("error") or "Prepare a PDF before sending.")
        recipient = (to or "").strip()
        mail_subject = (subject or "").strip()
        mail_body = (body or "").strip()
        if not recipient or "@" not in recipient:
            raise JobHuntError("Choose one contact email before sending.")
        try:
            policy.assert_can_send(recipient, mail_subject, mail_body)
        except EmailPolicyError as exc:
            raise JobHuntError(str(exc)) from exc
        pdf = self.store.pdf_path(record)
        sender = GmailSender(session)
        try:
            await sender.send_new(
                to=recipient,
                subject=mail_subject,
                body=mail_body,
                attachment=str(pdf),
            )
        except Exception as exc:  # noqa: BLE001
            self.store.update(
                application_id,
                to=recipient,
                subject=mail_subject,
                body=mail_body,
                status="ready",
                error=f"Gmail send failed: {exc}",
            )
            raise JobHuntError(f"Gmail send failed: {exc}") from exc
        policy.record_send(recipient, mail_subject)
        return self.store.update(
            application_id,
            to=recipient,
            subject=mail_subject,
            body=mail_body,
            status="sent",
            error="",
        )


def _title_from_paste(text: str) -> str:
    for line in text.splitlines():
        cleaned = " ".join(line.split())
        if len(cleaned) >= 4:
            return cleaned[:180]
    return "Pasted role"


def _model(settings: Settings) -> OpenAICompatibleModel | None:
    if not settings.api_key:
        return None
    try:
        return OpenAICompatibleModel(settings)
    except ValueError:
        return None


def _email_policy(settings: Settings) -> EmailPolicy:
    return EmailPolicy(
        enabled=settings.email_enabled,
        kill_path=settings.ribhus_dir / "email.killed",
        sends_per_minute=settings.email_rate_limit,
        sends_per_hour=settings.email_max_per_hour,
        cooldown_seconds=settings.email_cooldown,
    )
