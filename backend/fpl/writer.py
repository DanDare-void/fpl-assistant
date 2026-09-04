"""
Authenticated FPL write client.

Uses the x-api-authorization Bearer token from the Premier League OAuth2 system.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .session import FPLSession

logger = logging.getLogger(__name__)

BASE_URL = "https://fantasy.premierleague.com/api/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    ),
    "Content-Type": "application/json",
    "Origin": "https://fantasy.premierleague.com",
    "Referer": "https://fantasy.premierleague.com/transfers",
    "X-Requested-With": "XMLHttpRequest",
}


class FPLWriteError(Exception):
    pass


class FPLWriter:
    def __init__(self, session: FPLSession) -> None:
        self._session = session
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={
                **HEADERS,
                "x-api-authorization": session.auth_header(),
            },
            timeout=20.0,
            follow_redirects=True,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> FPLWriter:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def _get(self, path: str) -> Any:
        try:
            resp = await self._client.get(path)
            if resp.status_code == 401:
                raise FPLWriteError("Token expired or invalid. Please re-authenticate.")
            if resp.status_code == 403:
                raise FPLWriteError("Access denied. Please re-authenticate.")
            resp.raise_for_status()
            return resp.json()
        except FPLWriteError:
            raise
        except httpx.RequestError as exc:
            raise FPLWriteError(f"Network error: {exc}") from exc

    async def _post(self, path: str, payload: dict) -> Any:
        try:
            resp = await self._client.post(path, json=payload)
            if resp.status_code == 401:
                raise FPLWriteError("Token expired or invalid. Please re-authenticate.")
            if resp.status_code in (200, 201, 202):
                # FPL's transfers/ endpoint returns 200 with an empty body on success
                if not resp.content.strip():
                    return {}
                try:
                    return resp.json()
                except ValueError:
                    return {"raw": resp.text}
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            raise FPLWriteError(f"Request failed ({resp.status_code}): {detail}")
        except FPLWriteError:
            raise
        except httpx.RequestError as exc:
            raise FPLWriteError(f"Network error: {exc}") from exc

    async def get_me(self) -> dict[str, Any]:
        """Fetch authenticated user profile — used to validate the token."""
        return await self._get("me/")

    async def get_my_team(self, team_id: int) -> dict[str, Any]:
        """Fetch authenticated team data including selling prices."""
        return await self._get(f"my-team/{team_id}/")

    async def validate_session(self, team_id: int) -> bool:
        try:
            data = await self.get_me()
            return data.get("player") is not None
        except FPLWriteError:
            return False

    async def make_transfers(
        self,
        team_id: int,
        gameweek: int,
        transfers: list[dict[str, Any]],
        chip: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chips": chip,
            "entry": team_id,
            "event": gameweek,
            "transfers": transfers,
        }
        return await self._post("transfers/", payload)

    async def update_team(
        self,
        team_id: int,
        picks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return await self._post(f"my-team/{team_id}/", {"picks": picks})
