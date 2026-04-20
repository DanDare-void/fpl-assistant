"""
Manage routes — Claude recommendations + confirmed FPL write operations.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..claude.context import build_context
from ..claude.planner import generate_recommendations
from ..fpl import cache
from ..fpl.client import FPLClient, FPLClientError
from ..fpl.enrichment import enrich_players
from ..fpl.models import Bootstrap, Fixture, Squad
from ..fpl.session import get_session, is_authenticated
from ..fpl.writer import FPLWriter, FPLWriteError

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_auth():
    if not is_authenticated():
        raise HTTPException(
            status_code=401,
            detail="Not authenticated. Go to the Manage tab and enter your FPL session cookies.",
        )
    return get_session()


def _team_id() -> int:
    val = os.getenv("FPL_TEAM_ID")
    if not val:
        raise HTTPException(status_code=500, detail="FPL_TEAM_ID not configured")
    return int(val)


async def _load_fpl_data() -> tuple[Bootstrap, list[Fixture], Squad | None]:
    async with FPLClient() as client:
        cached_bs = await cache.get_cached_bootstrap()
        bootstrap = Bootstrap.model_validate(cached_bs) if cached_bs else await client.get_bootstrap()

        cached_fx = await cache.get_cached_fixtures()
        if cached_fx:
            fixtures = [Fixture.model_validate(f) for f in cached_fx]
        else:
            fixtures = await client.get_fixtures()

        # Use current GW for squad display, but next GW for transfers
        current_gw = next(
            (gw.id for gw in bootstrap.events if gw.is_current),
            next((gw.id for gw in bootstrap.events if gw.is_next), 1),
        )

        cached_sq = await cache.get_cached_squad(_team_id(), current_gw)
        squad = Squad.model_validate(cached_sq) if cached_sq else None

    return bootstrap, fixtures, squad


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------

@router.get("/api/manage/recommendations")
async def get_recommendations() -> dict:
    """
    Ask Claude for transfer + captain recommendations.
    Requires valid session to fetch selling prices from my-team endpoint.
    """
    session = _require_auth()
    team_id = _team_id()

    bootstrap, fixtures, squad = await _load_fpl_data()

    # Fetch authenticated my-team data (includes selling prices)
    async with FPLWriter(session) as writer:
        try:
            my_team = await writer.get_my_team(team_id)
        except FPLWriteError as exc:
            raise HTTPException(status_code=401, detail=str(exc))

    enriched = enrich_players(bootstrap, fixtures)
    context = build_context(bootstrap, fixtures, squad, enriched_players=enriched, detailed=True)

    # Determine free transfers — FPL nests this under transfers.limit
    transfers_info = my_team.get("transfers", {})
    free_transfers = (
        transfers_info.get("limit")
        or transfers_info.get("free")
        or 1
    )

    try:
        recs = await generate_recommendations(context, my_team, free_transfers)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "recommendations": recs,
        "free_transfers": free_transfers,
        "my_team": my_team,
    }


# ---------------------------------------------------------------------------
# Confirm transfers
# ---------------------------------------------------------------------------

class ConfirmTransferRequest(BaseModel):
    transfers: list[dict[str, Any]]   # [{element_in, element_out, purchase_price, selling_price}]
    chip: str | None = None


@router.post("/api/manage/transfers/confirm")
async def confirm_transfers(body: ConfirmTransferRequest) -> dict:
    """Submit confirmed transfers to FPL."""
    session = _require_auth()
    team_id = _team_id()

    bootstrap, _, _ = await _load_fpl_data()
    transfer_gw = next(
        (gw.id for gw in bootstrap.events if gw.is_next),
        next((gw.id for gw in bootstrap.events if gw.is_current), 1),
    )

    # Re-fetch live my-team data so selling prices and squad membership are authoritative
    async with FPLWriter(session) as writer:
        try:
            my_team = await writer.get_my_team(team_id)
        except FPLWriteError as exc:
            raise HTTPException(status_code=401, detail=str(exc))

    current_elements = {p["element"] for p in my_team.get("picks", [])}
    selling_price_map = {p["element"]: p["selling_price"] for p in my_team.get("picks", [])}
    purchase_price_map = {p.id: p.now_cost for p in bootstrap.elements}

    resolved = []
    for t in body.transfers:
        # Validate element_out is actually in the squad
        if t["element_out"] not in current_elements:
            raise HTTPException(
                status_code=400,
                detail=f"Player {t['element_out']} is not in your current squad.",
            )
        # Validate element_in exists in bootstrap
        actual_purchase_price = purchase_price_map.get(t["element_in"])
        if actual_purchase_price is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown player id {t['element_in']} for element_in.",
            )
        # Resolve selling price from live my-team data
        actual_selling_price = selling_price_map.get(t["element_out"])
        if actual_selling_price is None:
            raise HTTPException(
                status_code=400,
                detail=f"Could not determine selling price for player {t['element_out']}.",
            )
        resolved.append({
            "element_in": t["element_in"],
            "element_out": t["element_out"],
            "purchase_price": actual_purchase_price,
            "selling_price": actual_selling_price,
        })

    async with FPLWriter(session) as writer:
        try:
            result = await writer.make_transfers(
                team_id=team_id,
                gameweek=transfer_gw,
                transfers=resolved,
                chip=body.chip,
            )
        except FPLWriteError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    await cache.set_cached_squad(team_id, transfer_gw, {})
    logger.info("Transfers confirmed for GW%s: %s", transfer_gw, resolved)

    return {"status": "confirmed", "result": result}


# ---------------------------------------------------------------------------
# Confirm captain / bench
# ---------------------------------------------------------------------------

class ConfirmCaptainRequest(BaseModel):
    captain_id: int
    vice_captain_id: int


@router.post("/api/manage/captain/confirm")
async def confirm_captain(body: ConfirmCaptainRequest) -> dict:
    """Update captain and vice-captain, rebuilding picks entirely from live my-team data."""
    session = _require_auth()
    team_id = _team_id()

    # Re-fetch live picks — never trust the frontend's pick structure
    async with FPLWriter(session) as writer:
        try:
            my_team = await writer.get_my_team(team_id)
        except FPLWriteError as exc:
            raise HTTPException(status_code=401, detail=str(exc))

    current_elements = {p["element"] for p in my_team.get("picks", [])}

    # Validate both players are actually in the squad
    for pid, label in [(body.captain_id, "captain"), (body.vice_captain_id, "vice-captain")]:
        if pid not in current_elements:
            raise HTTPException(
                status_code=400,
                detail=f"Player {pid} is not in your squad and cannot be set as {label}.",
            )

    # Build picks from live data, only overriding captain flags
    picks = [
        {
            "element": p["element"],
            "position": p["position"],
            "is_captain": p["element"] == body.captain_id,
            "is_vice_captain": p["element"] == body.vice_captain_id,
        }
        for p in my_team["picks"]
    ]

    async with FPLWriter(session) as writer:
        try:
            result = await writer.update_team(team_id=team_id, picks=picks)
        except FPLWriteError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    logger.info("Captain set to %s, VC to %s for team %s", body.captain_id, body.vice_captain_id, team_id)
    return {"status": "confirmed", "result": result}
