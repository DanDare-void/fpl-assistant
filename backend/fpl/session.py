"""
In-memory FPL session store.

FPL now uses OAuth2 JWT Bearer tokens via the x-api-authorization header.
Tokens are stored in memory only — never persisted to disk.
They expire (typically 8 hours) and must be re-pasted when they do.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class FPLSession:
    bearer_token: str
    stored_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def auth_header(self) -> str:
        return f"Bearer {self.bearer_token}"

    def expires_at(self) -> datetime | None:
        """Decode the JWT exp claim without verifying the signature."""
        try:
            payload_b64 = self.bearer_token.split(".")[1]
            # Add padding
            padded = payload_b64 + "=" * (4 - len(payload_b64) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded))
            exp = payload.get("exp")
            return datetime.fromtimestamp(exp, tz=timezone.utc) if exp else None
        except Exception:
            return None

    def is_expired(self) -> bool:
        exp = self.expires_at()
        if exp is None:
            return False
        return datetime.now(timezone.utc) >= exp


# Module-level singleton
_session: FPLSession | None = None


def set_session(bearer_token: str) -> None:
    global _session
    _session = FPLSession(bearer_token=bearer_token)


def get_session() -> FPLSession | None:
    return _session


def clear_session() -> None:
    global _session
    _session = None


def is_authenticated() -> bool:
    if _session is None:
        return False
    if _session.is_expired():
        clear_session()
        return False
    return True
