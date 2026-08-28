"""
Manage routes — Claude recommendations + confirmed FPL write operations.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..claude.planner import generate_recommendations, generate_squad
from ..fpl import cache
from ..fpl.client import FPLClient
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
# Squad builder (new team / wildcard / free hit)
# ---------------------------------------------------------------------------

@router.get("/api/manage/build-squad")
async def build_squad(budget: float = 100.0) -> dict:
    """
    Ask Claude to build a 15-player squad from scratch within the given budget.
    No authentication required — purely advisory.
    """
    if budget < 50.0 or budget > 120.0:
        raise HTTPException(status_code=400, detail="Budget must be between 50 and 120.")

    bootstrap, fixtures, _ = await _load_fpl_data()
    enriched = enrich_players(bootstrap, fixtures)

    budget_tenths = round(budget * 10)

    # Build position candidate lists — top 25 per position by composite score,
    # only available players affordable within the budget.
    POSITIONS = ["GKP", "DEF", "MID", "FWD"]
    candidates: dict[str, list[dict]] = {}

    for pos in POSITIONS:
        pos_players = [
            p for p in enriched
            if p["position"] == pos
            and p["status"] == "a"
            and round(p["cost"] * 10) <= budget_tenths
        ]

        def _score(p: dict) -> float:
            fdr_penalty = (p["avg_fdr_3gw"] - 3) * 0.5
            return p["form"] + p["ppg"] * 0.5 + p["value_score"] - fdr_penalty

        pos_players.sort(key=_score, reverse=True)

        candidates[pos] = [
            {
                "player_id": p["id"],
                "name": p["name"],
                "team": p["team"],
                "cost_millions": p["cost"],
                "form": p["form"],
                "ppg": p["ppg"],
                "avg_fdr_3gw": p["avg_fdr_3gw"],
                "upcoming_fixtures": [
                    f"{f['opponent']}({'H' if f['home'] else 'A'}) FDR{f['fdr']}"
                    for f in p["upcoming_fixtures"][:3]
                ],
            }
            for p in pos_players[:25]
        ]

    try:
        result = await generate_squad(budget, candidates)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return result


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
    player_map = {p["id"]: p for p in enriched}

    # ---------------------------------------------------------------------------
    # Pre-compute everything — Claude does zero arithmetic, zero estimation
    # ---------------------------------------------------------------------------
    transfers_info = my_team.get("transfers", {})
    free_transfers = transfers_info.get("limit") or transfers_info.get("free") or 1
    bank_tenths = transfers_info.get("bank", 0)
    bank_m = round(bank_tenths / 10, 1)

    picks = my_team.get("picks", [])
    squad_ids = {p["element"] for p in picks}

    # Squad with exact selling prices
    squad_with_prices = []
    for p in picks:
        ep = player_map.get(p["element"], {})
        squad_with_prices.append({
            "player_id": p["element"],
            "name": ep.get("name", str(p["element"])),
            "position": ep.get("position", "?"),
            "team": ep.get("team", "?"),
            "selling_price_millions": round(p["selling_price"] / 10, 1),
            "form": ep.get("form", 0),
            "ppg": ep.get("ppg", 0),
            "avg_fdr_3gw": ep.get("avg_fdr_3gw", 3),
            "upcoming_fixtures": ep.get("upcoming_fixtures", [])[:3],
            "status": ep.get("status", "a"),
            "news": ep.get("news") or None,
            "is_captain": p.get("is_captain", False),
            "is_vice_captain": p.get("is_vice_captain", False),
            "is_starter": p["position"] <= 11,
        })

    # ---------------------------------------------------------------------------
    # Pre-rank all viable transfer pairs by impact score
    # Impact = form_gain weighted by fixture improvement
    # Net cost = in_cost - selling_price (exact, pre-computed)
    # Only include pairs affordable within the total possible budget
    # ---------------------------------------------------------------------------
    from ..fpl.enrichment import top_transfer_targets

    max_budget_tenths = bank_tenths + sum(p["selling_price"] for p in picks)

    viable_transfers: list[dict] = []
    for p in picks:
        ep_out = player_map.get(p["element"], {})
        selling_m = round(p["selling_price"] / 10, 1)
        pos = ep_out.get("position", "?")
        out_form = ep_out.get("form", 0.0)
        out_fdr = ep_out.get("avg_fdr_3gw", 3.0)

        targets = top_transfer_targets(enriched, position=pos, limit=20)
        for t in targets:
            if t["id"] in squad_ids:
                continue
            cost_tenths = round(t["cost"] * 10)
            if cost_tenths > max_budget_tenths:
                continue
            net_cost_m = round(t["cost"] - selling_m, 1)
            form_gain = round(t["form"] - out_form, 1)
            fdr_gain = round(out_fdr - t["avg_fdr_3gw"], 2)  # positive = better fixtures
            # Impact score: weighted form gain + fixture improvement bonus
            impact = form_gain + (fdr_gain * 1.5)

            viable_transfers.append({
                "out_player_id": p["element"],
                "out_name": ep_out.get("name", str(p["element"])),
                "out_position": pos,
                "out_selling_price_millions": selling_m,
                "out_form": out_form,
                "out_avg_fdr_3gw": out_fdr,
                "out_status": ep_out.get("status", "a"),
                "in_player_id": t["id"],
                "in_name": t["name"],
                "in_team": t["team"],
                "in_cost_millions": t["cost"],
                "in_form": t["form"],
                "in_ppg": t["ppg"],
                "in_avg_fdr_3gw": t["avg_fdr_3gw"],
                "in_upcoming_fixtures": t["upcoming_fixtures"][:3],
                "net_cost_millions": net_cost_m,
                "impact_score": round(impact, 2),
            })

    # Sort by impact descending — Claude works down this list greedily
    viable_transfers.sort(key=lambda x: x["impact_score"], reverse=True)

    # Deduplicate: only keep the best target per out-player (to avoid noise)
    # Claude can still pick a different target if it sees fit, but the top option is clear
    seen_out: set[int] = set()
    top_per_player: list[dict] = []
    rest: list[dict] = []
    for vt in viable_transfers:
        if vt["out_player_id"] not in seen_out:
            top_per_player.append(vt)
            seen_out.add(vt["out_player_id"])
        else:
            rest.append(vt)

    # Final ranked list: best option per player first, then alternatives
    ranked_transfers = top_per_player + rest[:20]

    # Chips playable next GW: bootstrap defines each chip's window; the
    # my-team response is authoritative on which the entry has already used.
    next_gw = next(
        (gw.id for gw in bootstrap.events if gw.is_next),
        next((gw.id for gw in bootstrap.events if gw.is_current), 1),
    )
    window_chips = {
        c.name for c in bootstrap.chips if c.start_event <= next_gw <= c.stop_event
    }
    team_chips = my_team.get("chips") or []
    if team_chips:
        unused = {c["name"] for c in team_chips if c.get("status_for_entry") == "available"}
        available_chips = sorted(unused & window_chips if window_chips else unused)
    else:
        available_chips = sorted(window_chips)

    planning_data = {
        "bank_millions": bank_m,
        "free_transfers": free_transfers,
        "total_possible_budget_millions": round(max_budget_tenths / 10, 1),
        "current_squad": squad_with_prices,
        "ranked_transfer_options": ranked_transfers,
        "available_chips": available_chips,
    }

    try:
        recs = await generate_recommendations(planning_data, free_transfers, available_chips)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "recommendations": recs,
        "free_transfers": free_transfers,
        "available_chips": available_chips,
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

    # Reject chip names the season doesn't have before they reach FPL
    if body.chip:
        valid_chips = {c.name for c in bootstrap.chips}
        if valid_chips and body.chip not in valid_chips:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown chip '{body.chip}'. This season's chips: {sorted(valid_chips)}.",
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

    # Running bank balance in tenths — simulate each transfer in sequence
    bank = my_team.get("transfers", {}).get("bank", 0)

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
        # Budget check — simulate running balance across chained transfers
        balance_after = bank + actual_selling_price - actual_purchase_price
        if balance_after < 0:
            p_in = next((p for p in bootstrap.elements if p.id == t["element_in"]), None)
            p_out = next((p for p in bootstrap.elements if p.id == t["element_out"]), None)
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Insufficient budget: bringing in {p_in.web_name if p_in else t['element_in']} "
                    f"(£{actual_purchase_price/10:.1f}m) for {p_out.web_name if p_out else t['element_out']} "
                    f"(sells for £{actual_selling_price/10:.1f}m) with £{bank/10:.1f}m in the bank "
                    f"leaves £{balance_after/10:.1f}m."
                ),
            )
        bank = balance_after
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
    # multiplier: 2 = captain, 0 = bench (position > 11), 1 = starter
    picks = []
    for p in my_team["picks"]:
        is_cap = p["element"] == body.captain_id
        is_bench = p["position"] > 11
        picks.append({
            "element": p["element"],
            "position": p["position"],
            "is_captain": is_cap,
            "is_vice_captain": p["element"] == body.vice_captain_id,
            "multiplier": 2 if is_cap else (0 if is_bench else 1),
        })

    async with FPLWriter(session) as writer:
        try:
            result = await writer.update_team(team_id=team_id, picks=picks)
        except FPLWriteError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    logger.info("Captain set to %s, VC to %s for team %s", body.captain_id, body.vice_captain_id, team_id)
    return {"status": "confirmed", "result": result}


class ConfirmLineupRequest(BaseModel):
    starters: list[int]  # 11 element ids
    bench: list[int]  # 4 element ids in bench order, GK first
    captain_id: int
    vice_captain_id: int


@router.post("/api/manage/lineup/confirm")
async def confirm_lineup(body: ConfirmLineupRequest) -> dict:
    """Set the full lineup: starting XI, bench order, captain and vice."""
    session = _require_auth()
    team_id = _team_id()

    async with FPLWriter(session) as writer:
        try:
            my_team = await writer.get_my_team(team_id)
        except FPLWriteError as exc:
            raise HTTPException(status_code=401, detail=str(exc))

    squad_ids = {p["element"] for p in my_team.get("picks", [])}
    requested = body.starters + body.bench
    if len(body.starters) != 11 or len(body.bench) != 4 or set(requested) != squad_ids or len(set(requested)) != 15:
        raise HTTPException(
            status_code=400,
            detail="starters (11) + bench (4) must be exactly the 15 players in the squad.",
        )
    for pid, label in [(body.captain_id, "captain"), (body.vice_captain_id, "vice-captain")]:
        if pid not in body.starters:
            raise HTTPException(status_code=400, detail=f"Player {pid} must be a starter to be {label}.")

    bootstrap, _, _ = await _load_fpl_data()
    etype = {p.id: p.element_type for p in bootstrap.elements}

    # Formation checks; FPL validates too, but fail fast with a clear message
    counts = {t: sum(1 for pid in body.starters if etype[pid] == t) for t in (1, 2, 3, 4)}
    if counts[1] != 1 or not (3 <= counts[2] <= 5) or not (2 <= counts[3] <= 5) or not (1 <= counts[4] <= 3):
        raise HTTPException(status_code=400, detail=f"Invalid formation: {counts}")
    if etype[body.bench[0]] != 1:
        raise HTTPException(status_code=400, detail="First bench slot must be the backup goalkeeper.")

    # Positions 1-11: XI ordered GK, DEF, MID, FWD (stable within input order)
    ordered_xi = sorted(body.starters, key=lambda pid: etype[pid])
    picks = []
    for pos, pid in enumerate(ordered_xi + body.bench, start=1):
        is_cap = pid == body.captain_id
        picks.append({
            "element": pid,
            "position": pos,
            "is_captain": is_cap,
            "is_vice_captain": pid == body.vice_captain_id,
            "multiplier": 2 if is_cap else (0 if pos > 11 else 1),
        })

    async with FPLWriter(session) as writer:
        try:
            result = await writer.update_team(team_id=team_id, picks=picks)
        except FPLWriteError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    logger.info("Lineup set for team %s: XI %s, bench %s", team_id, ordered_xi, body.bench)
    return {"status": "confirmed", "result": result}
