"""
Routes for squad, fixture, and player data.

All routes serve cached data where possible, falling back to stale cache
on FPL API errors rather than returning 500s.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from ..fpl.client import FPLClient, FPLClientError
from ..fpl.enrichment import enrich_players, top_transfer_targets, build_fdr_map
from ..fpl import cache

logger = logging.getLogger(__name__)
router = APIRouter()


def _team_id() -> int | None:
    val = os.getenv("FPL_TEAM_ID")
    return int(val) if val else None


async def _get_bootstrap(client: FPLClient) -> Any:
    cached = await cache.get_cached_bootstrap()
    if cached:
        from ..fpl.models import Bootstrap
        return Bootstrap.model_validate(cached)
    try:
        bootstrap = await client.get_bootstrap()
        await cache.set_cached_bootstrap(bootstrap.model_dump())
        return bootstrap
    except FPLClientError as exc:
        logger.warning("FPL bootstrap fetch failed, using stale: %s", exc)
        stale = await cache.get_stale_bootstrap()
        if stale:
            from ..fpl.models import Bootstrap
            return Bootstrap.model_validate(stale)
        raise HTTPException(status_code=503, detail="FPL data unavailable") from exc


async def _get_fixtures(client: FPLClient) -> list[Any]:
    cached = await cache.get_cached_fixtures()
    if cached:
        from ..fpl.models import Fixture
        return [Fixture.model_validate(f) for f in cached]
    try:
        fixtures = await client.get_fixtures()
        await cache.set_cached_fixtures([f.model_dump() for f in fixtures])
        return fixtures
    except FPLClientError as exc:
        logger.warning("FPL fixtures fetch failed, using stale: %s", exc)
        stale = await cache.get_stale_fixtures()
        if stale:
            from ..fpl.models import Fixture
            return [Fixture.model_validate(f) for f in stale]
        raise HTTPException(status_code=503, detail="FPL fixtures unavailable") from exc


@router.get("/api/squad")
async def get_squad(request: Request) -> dict:
    team_id = _team_id()
    if not team_id:
        raise HTTPException(status_code=400, detail="FPL_TEAM_ID not configured")

    async with FPLClient() as client:
        bootstrap = await _get_bootstrap(client)
        fixtures = await _get_fixtures(client)

        # Determine current gameweek. No is_current event means preseason —
        # the public picks endpoint 404s until the GW1 deadline passes.
        is_preseason = not any(gw.is_current for gw in bootstrap.events)
        current_gw = next(
            (gw.id for gw in bootstrap.events if gw.is_current),
            next((gw.id for gw in bootstrap.events if gw.is_next), 1),
        )

        # Try cache first
        cached_squad = await cache.get_cached_squad(team_id, current_gw)
        if cached_squad:
            from ..fpl.models import Squad
            squad = Squad.model_validate(cached_squad)
        else:
            try:
                squad = await client.get_squad(team_id, current_gw)
                await cache.set_cached_squad(team_id, current_gw, squad.model_dump())
            except FPLClientError as exc:
                logger.warning("Squad fetch failed, trying stale: %s", exc)
                stale = await cache.get_stale_squad(team_id, current_gw)
                if stale:
                    from ..fpl.models import Squad
                    squad = Squad.model_validate(stale)
                elif is_preseason:
                    return {
                        "gameweek": current_gw,
                        "preseason": True,
                        "message": (
                            "The season hasn't started yet — squad picks become "
                            "available after the first deadline. Use the Manage tab "
                            "to view or build your team in the meantime."
                        ),
                        "bank": 0.0,
                        "squad_value": 0.0,
                        "active_chip": None,
                        "event_transfers": 0,
                        "transfer_cost": 0,
                        "players": [],
                    }
                else:
                    raise HTTPException(status_code=503, detail="Squad data unavailable") from exc

    enriched = enrich_players(bootstrap, fixtures)
    player_map = {p["id"]: p for p in enriched}

    squad_players = []
    for pick in squad.picks:
        p = player_map.get(pick.element, {})
        squad_players.append({
            **p,
            "pick_position": pick.position,
            "is_captain": pick.is_captain,
            "is_vice_captain": pick.is_vice_captain,
            "multiplier": pick.multiplier,
            "is_starter": pick.position <= 11,
        })

    return {
        "gameweek": current_gw,
        "bank": squad.entry_history.bank / 10,
        "squad_value": squad.entry_history.value / 10,
        "active_chip": squad.active_chip or squad.entry_history.active_chip,
        "event_transfers": squad.entry_history.event_transfers,
        "transfer_cost": squad.entry_history.event_transfers_cost,
        "players": squad_players,
    }


@router.get("/api/fixtures")
async def get_fixtures(gameweek: int | None = None) -> dict:
    async with FPLClient() as client:
        bootstrap = await _get_bootstrap(client)
        fixtures = await _get_fixtures(client)

    team_map = {t.id: t.short_name for t in bootstrap.teams}

    if gameweek is not None:
        fixtures = [f for f in fixtures if f.event == gameweek]

    return {
        "fixtures": [
            {
                "id": f.id,
                "gameweek": f.event,
                "home_team": team_map.get(f.team_h, str(f.team_h)),
                "away_team": team_map.get(f.team_a, str(f.team_a)),
                "home_difficulty": f.team_h_difficulty,
                "away_difficulty": f.team_a_difficulty,
                "kickoff_time": f.kickoff_time,
                "finished": f.finished,
                "home_score": f.team_h_score,
                "away_score": f.team_a_score,
            }
            for f in fixtures
        ]
    }


@router.get("/api/players")
async def get_players(
    position: str | None = None,
    max_cost: float | None = None,
    limit: int = 20,
) -> dict:
    async with FPLClient() as client:
        bootstrap = await _get_bootstrap(client)
        fixtures = await _get_fixtures(client)

    enriched = enrich_players(bootstrap, fixtures)

    targets = top_transfer_targets(
        enriched,
        budget_max=max_cost,
        position=position,
        limit=limit,
    )

    return {"players": targets, "total": len(targets)}


@router.get("/api/fdr")
async def get_fdr(num_gameweeks: int = 6) -> dict:
    """Fixture difficulty ratings for all teams over the next N gameweeks."""
    async with FPLClient() as client:
        bootstrap = await _get_bootstrap(client)
        fixtures = await _get_fixtures(client)

    fdr_map = build_fdr_map(bootstrap, fixtures, num_gameweeks=num_gameweeks)
    team_map = {t.id: t.short_name for t in bootstrap.teams}

    return {
        "gameweeks": num_gameweeks,
        "teams": [
            {
                "team_id": team_id,
                "team": team_map.get(team_id, str(team_id)),
                "fixtures": team_fixtures,
            }
            for team_id, team_fixtures in fdr_map.items()
        ],
    }
