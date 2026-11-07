"""Orchestrate fetch → tailor → PDF → draft. Send is a separate approved step."""

from __future__ import annotations

import asyncio
import re
import shutil
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
    fetch_job_html,
    fetch_job_page,
    parse_posting,
    resume_highlights,
    resume_portfolio_url,
    resume_summary_sentence,
)
from ribhus.jobs.split import BATCH_LIMIT, collect_openings, parse_model_openings
from ribhus.jobs.store import JobStore
from ribhus.jobs.tailor import (
    BASE_RESUME_ATTACHED,
    explain_email,
    explain_resume,
    tailor_resume,
    write_application_email,
)
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
            "batch": self._latest_batch_view(),
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
                "resume_change": explain_resume(source, tailored),
                "email_why": explain_email(role, company),
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
                resume_change=BASE_RESUME_ATTACHED,
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

    async def prepare_batch(
        self,
        url: str = "",
        text: str = "",
        settings: Settings | None = None,
    ) -> dict[str, Any]:
        settings = settings or get_settings()
        source = self.store.read_resume()
        model = _model(settings)
        openings, omitted, note = await collect_openings(url, text, fetch=fetch_job_html)
        source_blob = "\n\n".join(str(item.get("text") or "") for item in openings)
        if len(openings) < 2 and model is not None and len(source_blob) >= 240:
            refined = await _model_openings(model, source_blob)
            if len(refined) >= 2:
                extra = max(0, len(refined) - BATCH_LIMIT)
                openings = refined[:BATCH_LIMIT]
                omitted = max(omitted, extra)
                note = "Split this text into separate openings."
                if extra:
                    note = f"{note} Prepared the first {BATCH_LIMIT}. Left out {extra}."
        batch = self.store.create_batch(
            {
                "source_url": (url or "").strip(),
                "status": "preparing",
                "note": note,
                "omitted": omitted,
                "error": "",
                "application_ids": [],
            }
        )
        folder = self.store.batch_folder(batch["id"])
        tex_path = folder / "resume.tex"
        pdf_path = folder / "resume_base.pdf"
        tex_path.write_text(source if source.endswith("\n") else source + "\n", encoding="utf-8")
        try:
            compile_resume(tex_path, pdf_path)
        except JobHuntError as exc:
            self.store.update_batch(batch["id"], status="failed", error=str(exc))
            raise
        name = applicant_name(source)
        summary = resume_summary_sentence(source)
        highlights = resume_highlights(source)
        portfolio = resume_portfolio_url(source)
        application_ids: list[str] = []
        try:
            for opening in openings:
                application_ids.append(
                    await self._draft_opening(
                        opening,
                        batch_id=batch["id"],
                        source=source,
                        pdf_path=pdf_path,
                        name=name,
                        summary=summary,
                        highlights=highlights,
                        portfolio=portfolio,
                        model=model,
                    )
                )
        except JobHuntError as exc:
            self.store.update_batch(
                batch["id"],
                status="failed",
                error=str(exc),
                application_ids=application_ids,
            )
            raise
        self.store.update_batch(
            batch["id"],
            status="review",
            error="",
            application_ids=application_ids,
        )
        return self.batch_view(batch["id"])

    def update_batch_items(self, batch_id: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        batch = self.store.get_batch(batch_id)
        allowed = {str(item) for item in batch.get("application_ids") or []}
        for item in items:
            app_id = str(item.get("id") or "")
            if app_id not in allowed:
                raise JobHuntError("That draft is not in this batch.")
            record = self.store.get(app_id)
            if record.get("status") == "sent":
                continue
            kept = bool(item.get("kept", True))
            recipient = str(item.get("to") or "").strip()
            subject = str(item.get("subject") or "").strip()
            body = str(item.get("body") or "").strip()
            fields: dict[str, Any] = {
                "kept": kept,
                "to": recipient,
                "subject": subject,
                "body": body,
            }
            if kept and "@" in recipient and record.get("status") == "skipped":
                fields["status"] = "ready"
                fields["error"] = ""
            self.store.update(app_id, **fields)
        self.store.update_batch(batch_id, status="review", error="")
        return self.batch_view(batch_id)

    async def send_next(
        self,
        batch_id: str,
        *,
        session: GmailSession,
        policy: EmailPolicy,
    ) -> dict[str, Any]:
        batch = self.store.get_batch(batch_id)
        self.store.update_batch(batch_id, status="sending")
        for app_id in list(batch.get("application_ids") or []):
            record = self.store.get(str(app_id))
            if record.get("kept") is False or record.get("status") == "sent":
                continue
            recipient = str(record.get("to") or "").strip()
            subject = str(record.get("subject") or "").strip()
            body = str(record.get("body") or "").strip()
            if record.get("status") == "skipped" and "@" not in recipient:
                continue
            if "@" not in recipient:
                self.store.update(
                    str(app_id),
                    status="skipped",
                    error="No contact email, so this one was not sent.",
                )
                continue
            try:
                await _wait_for_send(policy, recipient, subject, body)
            except JobHuntError as exc:
                self.store.update_batch(batch_id, status="review", error=str(exc))
                return self._step(batch_id, finished=False, stopped=True, sent_id=None)
            try:
                await self.send(
                    str(app_id),
                    to=recipient,
                    subject=subject,
                    body=body,
                    session=session,
                    policy=policy,
                )
            except JobHuntError as exc:
                self.store.update_batch(batch_id, status="review", error=str(exc))
                return self._step(batch_id, finished=False, stopped=True, sent_id=None)
            finished = self._batch_finished(batch_id)
            self.store.update_batch(
                batch_id,
                status="done" if finished else "sending",
                error="",
            )
            return self._step(
                batch_id,
                finished=finished,
                stopped=False,
                sent_id=str(app_id),
            )
        self.store.update_batch(batch_id, status="done", error="")
        return self._step(batch_id, finished=True, stopped=False, sent_id=None)

    def batch_view(self, batch_id: str) -> dict[str, Any]:
        batch = self.store.get_batch(batch_id)
        applications: list[dict[str, Any]] = []
        for app_id in batch.get("application_ids") or []:
            try:
                applications.append(self.store.get(str(app_id)))
            except JobHuntError:
                continue
        payload = dict(batch)
        payload["applications"] = applications
        return payload

    def _latest_batch_view(self) -> dict[str, Any] | None:
        latest = self.store.latest_batch()
        if latest is None:
            return None
        return self.batch_view(str(latest["id"]))

    def _step(
        self,
        batch_id: str,
        *,
        finished: bool,
        stopped: bool,
        sent_id: str | None,
    ) -> dict[str, Any]:
        return {
            "finished": finished,
            "stopped": stopped,
            "sent_id": sent_id,
            "batch": self.batch_view(batch_id),
        }

    def _batch_finished(self, batch_id: str) -> bool:
        batch = self.store.get_batch(batch_id)
        for app_id in batch.get("application_ids") or []:
            try:
                record = self.store.get(str(app_id))
            except JobHuntError:
                continue
            if record.get("kept") is False or record.get("status") in {"sent", "skipped"}:
                continue
            return False
        return True

    async def _draft_opening(
        self,
        opening: dict[str, Any],
        *,
        batch_id: str,
        source: str,
        pdf_path: Path,
        name: str,
        summary: str,
        highlights: list[str],
        portfolio: str,
        model: OpenAICompatibleModel | None,
    ) -> str:
        text = str(opening.get("text") or "")
        title = str(opening.get("title") or "")
        link = str(opening.get("url") or "")
        posting = parse_posting(title, text)
        role = posting["role"] or posting["department"] or "Role"
        company = posting["company"]
        emails = extract_emails(text)
        hint = str(opening.get("email") or "").strip().lower()
        if hint and hint in text.lower() and hint not in emails:
            emails.insert(0, hint)
        keywords = extract_keywords(text)
        fallback = draft_email(
            name=name,
            role=role,
            company=company,
            summary=summary,
            department=posting["department"],
            highlights=highlights,
            portfolio=portfolio,
            job_text=text,
        )
        subject, body = await write_application_email(
            model=model,
            name=name,
            role=role,
            company=company,
            department=posting["department"],
            summary=summary,
            job_text=text,
            fallback=fallback,
            highlights=highlights,
            portfolio=portfolio,
        )
        tailored, note = await tailor_resume(
            source,
            role=role,
            company=company,
            keywords=keywords,
            job_text=text,
            model=model,
        )
        change = explain_resume(source, tailored)
        pdf_file = f"resume_{company_slug(company)}.pdf"
        record = self.store.create(
            {
                "batch_id": batch_id,
                "kept": True,
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
                "resume_change": change,
                "email_why": explain_email(role, company),
                "status": "failed",
                "error": "",
            }
        )
        folder = self.store.folder(record["id"])
        tex_path = self.store.write_tex(
            record["id"],
            tailored if tailored.endswith("\n") else tailored + "\n",
        )
        target = folder / pdf_file
        try:
            compile_resume(tex_path, target)
        except JobHuntError as exc:
            tex_path.write_text(source if source.endswith("\n") else source + "\n", encoding="utf-8")
            try:
                compile_resume(tex_path, target)
            except JobHuntError as compile_exc:
                self.store.update(
                    record["id"],
                    status="failed",
                    error=str(compile_exc),
                    pdf_ready=False,
                )
                return str(record["id"])
            self.store.update(
                record["id"],
                status="ready",
                error="",
                pdf_ready=True,
                tailor_note=f"{note} The rewrite did not compile ({exc}). PDF is your base resume.",
                resume_change=BASE_RESUME_ATTACHED,
            )
            return str(record["id"])
        if not target.is_file() and pdf_path.is_file():
            shutil.copyfile(pdf_path, target)
        self.store.update(record["id"], status="ready", error="", pdf_ready=True)
        return str(record["id"])


_COOLDOWN_WAIT = re.compile(r"wait (\d+(?:\.\d+)?)s")


async def _wait_for_send(policy: EmailPolicy, to: str, subject: str, body: str) -> None:
    try:
        policy.assert_alive()
    except EmailPolicyError as exc:
        raise JobHuntError(str(exc)) from exc
    for _ in range(6):
        reason = policy.refuse_reason(to, subject, body)
        if reason is None:
            return
        if "sends/hour" in reason:
            raise JobHuntError(reason)
        match = _COOLDOWN_WAIT.search(reason)
        if match:
            await asyncio.sleep(float(match.group(1)) + 0.05)
            continue
        if "sends/minute" in reason:
            await asyncio.sleep(21)
            continue
        raise JobHuntError(reason)
    raise JobHuntError("Still waiting on the email pause. Try the next send again in a minute.")


async def _model_openings(model: OpenAICompatibleModel, source_blob: str) -> list[dict[str, str]]:
    try:
        response = await model.generate(
            [
                {
                    "role": "system",
                    "content": (
                        "Split the source into separate job openings. "
                        "Reply with JSON only: "
                        '{"openings": [{"role": "", "company": "", "email": "", "text": ""}]}. '
                        "Copy facts from the source. Do not invent emails, companies, or roles. "
                        "If there is only one opening, return {\"openings\": []}."
                    ),
                },
                {"role": "user", "content": source_blob[:12000]},
            ],
            max_tokens=1200,
        )
    except Exception:  # noqa: BLE001
        return []
    return parse_model_openings(response.text or "")


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
