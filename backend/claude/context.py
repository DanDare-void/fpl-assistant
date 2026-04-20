"""
Builds a compact, structured FPL context dict for injection into Claude prompts.

For chat (Haiku): target ~1500-2000 tokens.
For reports (Sonnet): can include more detail.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from ..fpl.models import Bootstrap, Fixture, Squad
from ..fpl.enrichment import (
    build_fdr_map,
    enrich_players,
    top_transfer_targets,
    average_fdr,
)

logger = logging.getLogger(__name__)

POSITION_LABELS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


def _current_gameweek(bootstrap: Bootstrap) -> int:
    for gw in bootstrap.events:
        if gw.is_current:
            return gw.id
    for gw in bootstrap.events:
        if gw.is_next:
            return gw.id
    return 1


def _next_deadline(bootstrap: Bootstrap) -> str | None:
    for gw in bootstrap.events:
        if gw.is_next:
            return gw.deadline_time
    return None


def build_context(
    bootstrap: Bootstrap,
    fixtures: list[Fixture],
    squad: Squad | None,
    enriched_players: list[dict[str, Any]] | None = None,
    league_standings: list[dict[str, Any]] | None = None,
    detailed: bool = False,
) -> dict[str, Any]:
    """
    Build the FPL context dict passed to Claude.

    Args:
        bootstrap: Parsed bootstrap data.
        fixtures: Full fixture list.
        squad: User's current squad (optional if team_id not configured).
        enriched_players: Pre-computed enriched player list (avoids recomputing).
        league_standings: Mini-league top entries (optional).
        detailed: If True, include more player data (for Sonnet reports).
    """
    if enriched_players is None:
        enriched_players = enrich_players(bootstrap, fixtures)

    player_map: dict[int, dict[str, Any]] = {p["id"]: p for p in enriched_players}
    current_gw = _current_gameweek(bootstrap)
    next_deadline = _next_deadline(bootstrap)

    ctx: dict[str, Any] = {
        "current_gameweek": current_gw,
        "next_deadline": next_deadline,
    }

    # --- Squad section ---
    if squad is not None:
        bank = squad.entry_history.bank / 10
        squad_value = squad.entry_history.value / 10
        active_chip = squad.active_chip or squad.entry_history.active_chip

        squad_players = []
        for pick in squad.picks:
            p = player_map.get(pick.element)
            if p is None:
                continue
            squad_players.append({
                "name": p["name"],
                "team": p["team"],
                "position": p["position"],
                "cost": p["cost"],
                "form": p["form"],
                "ppg": p["ppg"],
                "status": p["status"],
                "news": p["news"] or None,
                "is_captain": pick.is_captain,
                "is_vice_captain": pick.is_vice_captain,
                "is_starter": pick.position <= 11,
                "upcoming_fixtures": p.get("upcoming_fixtures", [])[:3],
            })

        ctx["squad"] = {
            "bank": bank,
            "squad_value": squad_value,
            "active_chip": active_chip,
            "event_transfers": squad.entry_history.event_transfers,
            "transfer_cost": squad.entry_history.event_transfers_cost,
            "players": squad_players,
        }

    # --- Top transfer targets by position ---
    budget = (ctx.get("squad", {}).get("bank", 0) + 0.1)  # slight buffer
    ctx["transfer_targets"] = {
        pos: top_transfer_targets(
            enriched_players,
            budget_max=None,  # let Claude filter by squad budget
            position=pos,
            limit=5 if not detailed else 10,
        )
        for pos in ["GKP", "DEF", "MID", "FWD"]
    }

    # --- Best/worst upcoming schedules (top 6 easiest teams) ---
    fdr_map = build_fdr_map(bootstrap, fixtures, num_gameweeks=3)
    team_fdr = []
    for team in bootstrap.teams:
        team_fixtures = fdr_map.get(team.id, [])
        team_fdr.append({
            "team": team.short_name,
            "avg_fdr_3gw": average_fdr(team_fixtures, 3),
            "fixtures": team_fixtures[:3],
        })
    team_fdr.sort(key=lambda x: x["avg_fdr_3gw"])
    ctx["easiest_schedules"] = team_fdr[:6]
    ctx["hardest_schedules"] = team_fdr[-4:]

    # --- Mini-league ---
    if league_standings:
        ctx["mini_league"] = league_standings[:10]

    return ctx
