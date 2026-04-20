"""
Auth routes — store/clear FPL Bearer token in memory.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..fpl.session import set_session, get_session, clear_session, is_authenticated
from ..fpl.writer import FPLWriter

router = APIRouter()


class SessionRequest(BaseModel):
    bearer_token: str


@router.post("/api/auth/session")
async def store_session(body: SessionRequest) -> dict:
    """Store FPL Bearer token and validate it against the API."""
    token = body.bearer_token.strip()
    # Strip 'Bearer ' prefix if the user pasted the full header value
    if token.lower().startswith("bearer "):
        token = token[7:].strip()

    set_session(token)

    session = get_session()
    team_id = int(os.getenv("FPL_TEAM_ID", "0"))
    if not team_id:
        raise HTTPException(status_code=500, detail="FPL_TEAM_ID not configured")

    async with FPLWriter(session) as writer:
        valid = await writer.validate_session(team_id)

    if not valid:
        clear_session()
        raise HTTPException(
            status_code=401,
            detail="Token is invalid or expired. Copy a fresh x-api-authorization value from DevTools.",
        )

    exp = session.expires_at()
    return {
        "authenticated": True,
        "stored_at": session.stored_at.isoformat(),
        "expires_at": exp.isoformat() if exp else None,
    }


@router.delete("/api/auth/session")
async def logout() -> dict:
    clear_session()
    return {"authenticated": False}


@router.get("/api/auth/status")
async def auth_status() -> dict:
    session = get_session()
    if not is_authenticated():
        return {"authenticated": False}
    exp = session.expires_at()
    return {
        "authenticated": True,
        "stored_at": session.stored_at.isoformat(),
        "expires_at": exp.isoformat() if exp else None,
    }
