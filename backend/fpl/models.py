from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Bootstrap — element types (positions)
# ---------------------------------------------------------------------------

class ElementType(BaseModel):
    id: int
    singular_name: str
    singular_name_short: str
    plural_name: str
    plural_name_short: str


# ---------------------------------------------------------------------------
# Bootstrap — teams
# ---------------------------------------------------------------------------

class Team(BaseModel):
    id: int
    name: str
    short_name: str
    strength: int
    strength_overall_home: int
    strength_overall_away: int
    strength_attack_home: int
    strength_attack_away: int
    strength_defence_home: int
    strength_defence_away: int


# ---------------------------------------------------------------------------
# Bootstrap — gameweeks (events)
# ---------------------------------------------------------------------------

class Gameweek(BaseModel):
    id: int
    name: str
    deadline_time: str
    finished: bool
    is_current: bool
    is_next: bool
    average_entry_score: int | None = None
    highest_score: int | None = None
    chip_plays: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Bootstrap — players (elements)
# ---------------------------------------------------------------------------

class Player(BaseModel):
    id: int
    first_name: str
    second_name: str
    web_name: str
    team: int                       # team id
    element_type: int               # position id
    now_cost: int                   # cost in tenths (e.g. 65 = £6.5m)
    total_points: int
    form: str                       # string float from API
    points_per_game: str
    selected_by_percent: str
    minutes: int
    goals_scored: int
    assists: int
    clean_sheets: int
    goals_conceded: int
    yellow_cards: int
    red_cards: int
    saves: int
    bonus: int
    bps: int
    influence: str
    creativity: str
    threat: str
    ict_index: str
    transfers_in_event: int
    transfers_out_event: int
    status: str                     # 'a' available, 'i' injured, 'd' doubtful, 's' suspended, 'u' unavailable
    news: str
    chance_of_playing_next_round: int | None = None
    chance_of_playing_this_round: int | None = None

    @property
    def cost(self) -> float:
        return self.now_cost / 10

    @property
    def form_float(self) -> float:
        try:
            return float(self.form)
        except ValueError:
            return 0.0

    @property
    def ppg_float(self) -> float:
        try:
            return float(self.points_per_game)
        except ValueError:
            return 0.0

    @property
    def value_score(self) -> float:
        """Points per game per million — a simple value metric."""
        return round(self.ppg_float / self.cost, 3) if self.cost else 0.0


# ---------------------------------------------------------------------------
# Bootstrap — full response
# ---------------------------------------------------------------------------

class Bootstrap(BaseModel):
    events: list[Gameweek]
    teams: list[Team]
    elements: list[Player]
    element_types: list[ElementType]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class Fixture(BaseModel):
    id: int
    event: int | None = None        # gameweek number; None if unscheduled
    team_h: int
    team_a: int
    team_h_difficulty: int
    team_a_difficulty: int
    finished: bool
    kickoff_time: str | None = None
    team_h_score: int | None = None
    team_a_score: int | None = None


# ---------------------------------------------------------------------------
# Squad picks
# ---------------------------------------------------------------------------

class Pick(BaseModel):
    element: int                    # player id
    position: int                   # 1-15 (1-11 starting, 12-15 bench)
    multiplier: int                 # 1 normal, 2 captain, 0 benched
    is_captain: bool
    is_vice_captain: bool


class EntryEvent(BaseModel):
    points: int
    total_points: int
    rank: int | None = None
    overall_rank: int | None = None
    bank: int                       # tenths of a million
    value: int                      # squad value in tenths
    event_transfers: int
    event_transfers_cost: int
    active_chip: str | None = None


class Squad(BaseModel):
    active_chip: str | None = None
    entry_history: EntryEvent
    picks: list[Pick]


# ---------------------------------------------------------------------------
# Player history / fixtures (element-summary endpoint)
# ---------------------------------------------------------------------------

class PlayerFixture(BaseModel):
    event: int
    opponent_short_title: str = Field(alias="opponent_short_title", default="")
    is_home: bool
    difficulty: int
    kickoff_time: str | None = None

    model_config = {"populate_by_name": True}


class PlayerHistorySeason(BaseModel):
    season_name: str
    total_points: int
    minutes: int


class PlayerDetail(BaseModel):
    fixtures: list[PlayerFixture]
    history: list[dict[str, Any]]
    history_past: list[PlayerHistorySeason]


# ---------------------------------------------------------------------------
# Live scores
# ---------------------------------------------------------------------------

class LiveElement(BaseModel):
    id: int
    stats: dict[str, Any]


class LiveScore(BaseModel):
    elements: list[LiveElement]


# ---------------------------------------------------------------------------
# Mini-league standings
# ---------------------------------------------------------------------------

class LeagueEntry(BaseModel):
    id: int
    entry_name: str
    player_name: str
    rank: int
    last_rank: int
    total: int
    event_total: int


class LeagueStandings(BaseModel):
    league: dict[str, Any]
    standings: list[LeagueEntry]
