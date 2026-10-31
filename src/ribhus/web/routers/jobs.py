"""Dashboard API for the job-hunt module."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ribhus.channels.gmail_web.policy import EmailPolicy
from ribhus.channels.gmail_web.session import GmailSession
from ribhus.config import get_settings
from ribhus.jobs.errors import JobHuntError
from ribhus.jobs.service import JobHuntService
from ribhus.web.auth import AuthDep

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class ResumeBody(BaseModel):
    tex: str = Field(min_length=1)


class PrepareBody(BaseModel):
    url: str = ""
    text: str = ""


class SendBody(BaseModel):
    to: str = Field(min_length=3)
    subject: str = Field(min_length=1)
    body: str = Field(min_length=1)


def _service() -> JobHuntService:
    settings = get_settings()
    return JobHuntService(settings.ribhus_dir / "job_hunt")


def _session(request: Request) -> GmailSession:
    existing = getattr(request.app.state, "job_gmail_session", None)
    if isinstance(existing, GmailSession):
        return existing
    settings = get_settings()
    session = GmailSession(
        user_data_dir=settings.ribhus_dir / "gmail_profile",
        headed=settings.email_headed,
        login_timeout=settings.email_login_timeout,
    )
    request.app.state.job_gmail_session = session
    return session


def _policy(request: Request) -> EmailPolicy:
    existing = getattr(request.app.state, "job_email_policy", None)
    if isinstance(existing, EmailPolicy):
        return existing
    settings = get_settings()
    policy = EmailPolicy(
        enabled=settings.email_enabled,
        kill_path=settings.ribhus_dir / "email.killed",
        sends_per_minute=settings.email_rate_limit,
        sends_per_hour=settings.email_max_per_hour,
        cooldown_seconds=settings.email_cooldown,
    )
    request.app.state.job_email_policy = policy
    return policy


def _http(exc: JobHuntError) -> HTTPException:
    missing = "not found" in str(exc).lower()
    return HTTPException(status_code=404 if missing else 400, detail=str(exc))


@router.get("/status")
def job_status(_: AuthDep) -> dict[str, Any]:
    return _service().status()


@router.put("/resume")
def save_resume(body: ResumeBody, _: AuthDep) -> dict[str, Any]:
    try:
        return _service().save_resume(body.tex)
    except JobHuntError as exc:
        raise _http(exc) from exc


@router.post("/applications")
async def prepare_application(body: PrepareBody, _: AuthDep) -> dict[str, Any]:
    try:
        return await _service().prepare(body.url, body.text)
    except JobHuntError as exc:
        raise _http(exc) from exc


@router.get("/applications/{application_id}/pdf")
def application_pdf(application_id: str, _: AuthDep) -> FileResponse:
    try:
        path = _service().pdf_file(application_id)
    except JobHuntError as exc:
        raise _http(exc) from exc
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@router.post("/applications/{application_id}/send")
async def send_application(
    application_id: str,
    body: SendBody,
    request: Request,
    _: AuthDep,
) -> dict[str, Any]:
    try:
        return await _service().send(
            application_id,
            to=body.to,
            subject=body.subject,
            body=body.body,
            session=_session(request),
            policy=_policy(request),
        )
    except JobHuntError as exc:
        raise _http(exc) from exc


@router.post("/gmail/connect")
async def connect_gmail(request: Request, _: AuthDep) -> dict[str, Any]:
    session = _session(request)
    try:
        await session.ensure_logged_in()
        state = await session.login_state()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "logged_in": bool(state.get("logged_in")),
        "profile": str(session.user_data_dir),
    }
