"""Ephemeral session token auth for the dashboard (loopback-first)."""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Query, status

_SESSION_TOKEN: str = secrets.token_urlsafe(32)


def get_session_token() -> str:
    return _SESSION_TOKEN


def rotate_session_token() -> str:
    global _SESSION_TOKEN
    _SESSION_TOKEN = secrets.token_urlsafe(32)
    return _SESSION_TOKEN


def require_token(
    authorization: Annotated[str | None, Header()] = None,
    token: Annotated[str | None, Query()] = None,
) -> None:
    provided: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        provided = authorization[7:].strip()
    elif token:
        provided = token.strip()
    if not provided or not secrets.compare_digest(provided, _SESSION_TOKEN):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing session token",
        )


AuthDep = Annotated[None, Depends(require_token)]
