"""
Async HTTP client for the FPL API.

All methods return parsed Pydantic models. Callers should handle
FPLClientError for any network or schema problem.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .models import (
    Bootstrap,
    Fixture,
    Squad,
    PlayerDetail,
    LiveScore,
    LeagueStandings,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://fantasy.premierleague.com/api/"

# The FPL site blocks default Python user-agents; mimic a browser.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}


class FPLClientError(Exception):
    """Raised when the FPL API returns an error or unexpected response."""


class FPLClient:
    def __init__(self, timeout: float = 20.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers=HEADERS,
            timeout=timeout,
            follow_redirects=True,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> FPLClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_json(self, path: str) -> Any:
        try:
            response = await self._client.get(path)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            raise FPLClientError(
                f"HTTP {exc.response.status_code} from FPL API: {path}"
            ) from exc
        except httpx.RequestError as exc:
            raise FPLClientError(f"Network error fetching {path}: {exc}") from exc
        except Exception as exc:
            raise FPLClientError(f"Unexpected error fetching {path}: {exc}") from exc

    # ------------------------------------------------------------------
    # Public endpoints
    # ------------------------------------------------------------------

    async def get_bootstrap(self) -> Bootstrap:
        """Fetch master data — players, teams, gameweeks, element types."""
        data = await self._get_json("bootstrap-static/")
        try:
            return Bootstrap.model_validate(data)
        except Exception as exc:
            raise FPLClientError(f"Failed to parse bootstrap data: {exc}") from exc

    async def get_fixtures(self, gameweek: int | None = None) -> list[Fixture]:
        """Fetch all fixtures, or fixtures for a specific gameweek."""
        path = "fixtures/" if gameweek is None else f"fixtures/?event={gameweek}"
        data = await self._get_json(path)
        try:
            return [Fixture.model_validate(f) for f in data]
        except Exception as exc:
            raise FPLClientError(f"Failed to parse fixtures data: {exc}") from exc

    async def get_squad(self, team_id: int, gameweek: int) -> Squad:
        """Fetch squad picks for a given team and gameweek."""
        data = await self._get_json(f"entry/{team_id}/event/{gameweek}/picks/")
        try:
            return Squad.model_validate(data)
        except Exception as exc:
            raise FPLClientError(f"Failed to parse squad data: {exc}") from exc

    async def get_player_detail(self, player_id: int) -> PlayerDetail:
        """Fetch full history and upcoming fixtures for a player."""
        data = await self._get_json(f"element-summary/{player_id}/")
        try:
            return PlayerDetail.model_validate(data)
        except Exception as exc:
            raise FPLClientError(
                f"Failed to parse player detail for {player_id}: {exc}"
            ) from exc

    async def get_live_scores(self, gameweek: int) -> LiveScore:
        """Fetch live gameweek scores."""
        data = await self._get_json(f"event/{gameweek}/live/")
        try:
            return LiveScore.model_validate(data)
        except Exception as exc:
            raise FPLClientError(
                f"Failed to parse live scores for GW{gameweek}: {exc}"
            ) from exc

    async def get_league_standings(self, league_id: int) -> LeagueStandings:
        """Fetch mini-league standings."""
        data = await self._get_json(f"leagues-classic/{league_id}/standings/")
        try:
            standings_data = {
                "league": data.get("league", {}),
                "standings": data.get("standings", {}).get("results", []),
            }
            return LeagueStandings.model_validate(standings_data)
        except Exception as exc:
            raise FPLClientError(
                f"Failed to parse league standings for {league_id}: {exc}"
            ) from exc

    async def get_team_info(self, team_id: int) -> dict[str, Any]:
        """Fetch team metadata."""
        return await self._get_json(f"entry/{team_id}/")

    async def get_transfer_history(self, team_id: int) -> list[dict[str, Any]]:
        """Fetch transfer history for a team."""
        return await self._get_json(f"entry/{team_id}/transfers/")

    async def get_season_history(self, team_id: int) -> dict[str, Any]:
        """Fetch season history and chip usage for a team."""
        return await self._get_json(f"entry/{team_id}/history/")
