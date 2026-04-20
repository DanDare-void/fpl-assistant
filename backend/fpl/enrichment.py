"""
Derived stats and enrichment on top of raw FPL data.

These functions take parsed models and produce compact summaries ready
for injecting into Claude prompts or returning via the API.
"""

from __future__ import annotations

from typing import Any

from .models import Bootstrap, Fixture, Player, Team


# ---------------------------------------------------------------------------
# Fixture difficulty rating (FDR) helpers
# ---------------------------------------------------------------------------

def build_fdr_map(
    bootstrap: Bootstrap,
    fixtures: list[Fixture],
    num_gameweeks: int = 6,
) -> dict[int, list[dict[str, Any]]]:
    """
    Build a per-team upcoming fixture list with difficulty ratings.

    Returns a dict of {team_id: [{"gw": int, "opponent": str, "home": bool, "fdr": int}, ...]}.
    Only includes unfinished fixtures for the next `num_gameweeks` gameweeks.
    """
    team_map: dict[int, str] = {t.id: t.short_name for t in bootstrap.teams}

    # Determine current gameweek
    current_gw = next(
        (gw.id for gw in bootstrap.events if gw.is_current),
        next((gw.id for gw in bootstrap.events if gw.is_next), 1),
    )
    max_gw = current_gw + num_gameweeks - 1

    fdr: dict[int, list[dict[str, Any]]] = {t.id: [] for t in bootstrap.teams}

    for fixture in fixtures:
        if fixture.finished:
            continue
        if fixture.event is None:
            continue
        if not (current_gw <= fixture.event <= max_gw):
            continue

        fdr[fixture.team_h].append({
            "gw": fixture.event,
            "opponent": team_map.get(fixture.team_a, "?"),
            "home": True,
            "fdr": fixture.team_h_difficulty,
        })
        fdr[fixture.team_a].append({
            "gw": fixture.event,
            "opponent": team_map.get(fixture.team_h, "?"),
            "home": False,
            "fdr": fixture.team_a_difficulty,
        })

    # Sort each team's fixtures by gameweek
    for team_id in fdr:
        fdr[team_id].sort(key=lambda x: x["gw"])

    return fdr


def average_fdr(fixtures: list[dict[str, Any]], num_gws: int = 3) -> float:
    """Average FDR for the next N fixtures."""
    upcoming = fixtures[:num_gws]
    if not upcoming:
        return 5.0
    return round(sum(f["fdr"] for f in upcoming) / len(upcoming), 2)


# ---------------------------------------------------------------------------
# Player enrichment
# ---------------------------------------------------------------------------

def enrich_players(
    bootstrap: Bootstrap,
    fixtures: list[Fixture],
    num_fdr_gws: int = 6,
) -> list[dict[str, Any]]:
    """
    Return a list of enriched player dicts, adding:
      - team_short_name
      - position_short (GKP/DEF/MID/FWD)
      - cost (float)
      - form_float
      - ppg_float
      - value_score
      - avg_fdr_3gw
      - upcoming_fixtures (next 6 GW FDR list)
    """
    fdr_map = build_fdr_map(bootstrap, fixtures, num_fdr_gws)
    team_map: dict[int, str] = {t.id: t.short_name for t in bootstrap.teams}
    pos_map: dict[int, str] = {
        et.id: et.singular_name_short for et in bootstrap.element_types
    }

    enriched = []
    for player in bootstrap.elements:
        player_fixtures = fdr_map.get(player.team, [])
        enriched.append({
            "id": player.id,
            "name": player.web_name,
            "full_name": f"{player.first_name} {player.second_name}",
            "team": team_map.get(player.team, "?"),
            "team_id": player.team,
            "position": pos_map.get(player.element_type, "?"),
            "cost": player.cost,
            "total_points": player.total_points,
            "form": player.form_float,
            "ppg": player.ppg_float,
            "value_score": player.value_score,
            "selected_by_pct": float(player.selected_by_percent),
            "minutes": player.minutes,
            "goals": player.goals_scored,
            "assists": player.assists,
            "clean_sheets": player.clean_sheets,
            "status": player.status,
            "news": player.news,
            "chance_next": player.chance_of_playing_next_round,
            "transfers_in_gw": player.transfers_in_event,
            "transfers_out_gw": player.transfers_out_event,
            "avg_fdr_3gw": average_fdr(player_fixtures, 3),
            "upcoming_fixtures": player_fixtures[:num_fdr_gws],
        })

    return enriched


# ---------------------------------------------------------------------------
# Top transfer targets
# ---------------------------------------------------------------------------

def top_transfer_targets(
    enriched_players: list[dict[str, Any]],
    budget_max: float | None = None,
    position: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Rank players by a composite score: form + value_score, weighted by FDR.

    Filters:
      - Only available players (status == 'a')
      - Optional max cost filter
      - Optional position filter (GKP/DEF/MID/FWD)
    """
    candidates = [
        p for p in enriched_players
        if p["status"] == "a"
        and (budget_max is None or p["cost"] <= budget_max)
        and (position is None or p["position"] == position)
        and p["form"] > 0
    ]

    def score(p: dict[str, Any]) -> float:
        # Reward form and value, penalise tough upcoming fixtures
        fdr_penalty = (p["avg_fdr_3gw"] - 3) * 0.5  # 0 at FDR=3, +1 at FDR=5
        return p["form"] + p["value_score"] * 2 - fdr_penalty

    candidates.sort(key=score, reverse=True)
    return candidates[:limit]


# ---------------------------------------------------------------------------
# Squad context summary (for Claude prompts)
# ---------------------------------------------------------------------------

def squad_summary(
    picks: list[dict[str, Any]],         # from Squad.picks, with player data merged
    bank: float,
    squad_value: float,
    active_chip: str | None,
    current_gw: int,
) -> dict[str, Any]:
    """
    Produce a compact summary of the user's squad for the Claude context prompt.
    """
    starters = [p for p in picks if p["position"] <= 11]
    bench = [p for p in picks if p["position"] > 11]

    captain = next((p for p in picks if p.get("is_captain")), None)
    vice = next((p for p in picks if p.get("is_vice_captain")), None)

    return {
        "gameweek": current_gw,
        "bank": bank,
        "squad_value": squad_value,
        "active_chip": active_chip,
        "captain": captain["name"] if captain else None,
        "vice_captain": vice["name"] if vice else None,
        "starters": [
            {
                "name": p["name"],
                "position": p["position_label"],
                "team": p["team"],
                "cost": p["cost"],
                "form": p["form"],
                "ppg": p["ppg"],
                "status": p["status"],
                "news": p["news"] or None,
                "upcoming_fixtures": p.get("upcoming_fixtures", [])[:3],
            }
            for p in starters
        ],
        "bench": [
            {
                "name": p["name"],
                "position": p["position_label"],
                "team": p["team"],
                "cost": p["cost"],
            }
            for p in bench
        ],
    }
