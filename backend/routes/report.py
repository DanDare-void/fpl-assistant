"""
Report routes.

GET  /api/report/latest   — fetch the most recent stored report
POST /api/report/generate — trigger an on-demand report generation
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException

from ..claude.client import ClaudeClient
from ..claude.context import build_context
from ..claude.prompts import build_report_system_prompt
from ..fpl.client import FPLClient, FPLClientError
from ..fpl.enrichment import enrich_players
from ..fpl.models import Bootstrap, Fixture, Squad
from ..fpl import cache

logger = logging.getLogger(__name__)
router = APIRouter()


def _team_id() -> int | None:
    val = os.getenv("FPL_TEAM_ID")
    return int(val) if val else None


async def _generate_and_store(gameweek: int) -> str:
    """Core report generation logic — fetch context, call Claude, store result."""
    async with FPLClient() as client:
        # Bootstrap
        cached_bs = await cache.get_cached_bootstrap()
        if cached_bs:
            bootstrap = Bootstrap.model_validate(cached_bs)
        else:
            bootstrap = await client.get_bootstrap()
            await cache.set_cached_bootstrap(bootstrap.model_dump())

        # Fixtures
        cached_fx = await cache.get_cached_fixtures()
        if cached_fx:
            fixtures = [Fixture.model_validate(f) for f in cached_fx]
        else:
            fixtures = await client.get_fixtures()
            await cache.set_cached_fixtures([f.model_dump() for f in fixtures])

        # Squad
        squad = None
        team_id = _team_id()
        if team_id:
            cached_sq = await cache.get_cached_squad(team_id, gameweek)
            if cached_sq:
                squad = Squad.model_validate(cached_sq)
            else:
                try:
                    squad = await client.get_squad(team_id, gameweek)
                    await cache.set_cached_squad(team_id, gameweek, squad.model_dump())
                except FPLClientError as exc:
                    logger.warning("Squad unavailable for report: %s", exc)

    enriched = enrich_players(bootstrap, fixtures)
    context = build_context(
        bootstrap, fixtures, squad, enriched_players=enriched, detailed=True
    )

    system_prompt = build_report_system_prompt(gameweek)
    context_message = (
        f"Please generate the GW{gameweek} briefing using this FPL data:\n\n"
        f"```json\n{json.dumps(context, indent=2)}\n```"
    )

    claude = ClaudeClient()
    report_text = await claude.generate_report(system_prompt, context_message)

    await cache.save_report(gameweek, report_text)
    logger.info("Report generated and stored for GW%s", gameweek)
    return report_text


@router.get("/api/report/latest")
async def get_latest_report() -> dict:
    report = await cache.get_latest_report()
    if report is None:
        raise HTTPException(
            status_code=404,
            detail="No report available yet. Use POST /api/report/generate to create one.",
        )
    return report


@router.get("/api/report/{gameweek}")
async def get_report_for_gameweek(gameweek: int) -> dict:
    report = await cache.get_report_for_gameweek(gameweek)
    if report is None:
        raise HTTPException(
            status_code=404,
            detail=f"No report found for GW{gameweek}.",
        )
    return report


@router.post("/api/report/generate")
async def generate_report(background_tasks: BackgroundTasks) -> dict:
    """
    Trigger report generation for the current/next gameweek.
    Runs in the background and returns immediately.
    """
    # Find the target gameweek from cache (avoid a live API call just for this)
    cached_bs = await cache.get_stale_bootstrap()
    if cached_bs is None:
        raise HTTPException(
            status_code=503,
            detail="No FPL data in cache. Ensure the app has started and fetched data.",
        )

    from ..fpl.models import Bootstrap as BS
    bootstrap = BS.model_validate(cached_bs)
    current_gw = next(
        (gw.id for gw in bootstrap.events if gw.is_current),
        next((gw.id for gw in bootstrap.events if gw.is_next), 1),
    )

    async def run() -> None:
        try:
            await _generate_and_store(current_gw)
        except Exception as exc:
            logger.error("Report generation failed for GW%s: %s", current_gw, exc)

    background_tasks.add_task(run)

    return {
        "status": "generating",
        "gameweek": current_gw,
        "message": f"Report generation started for GW{current_gw}. "
                   "Poll GET /api/report/latest to retrieve it.",
    }
