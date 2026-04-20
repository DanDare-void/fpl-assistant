"""
SQLite caching layer for FPL API responses.

Each cache entry stores raw JSON alongside a timestamp. Callers check
is_stale() before deciding whether to re-fetch from the API.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from ..db import get_db

logger = logging.getLogger(__name__)

# Cache TTLs
TTL_BOOTSTRAP_HOURS = 4
TTL_FIXTURES_HOURS = 24
TTL_SQUAD_HOURS = 4
TTL_PLAYER_HISTORY_HOURS = 24
TTL_LIVE_SCORES_MINUTES = 5


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_stale(fetched_at_iso: str, ttl_seconds: int) -> bool:
    fetched_at = datetime.fromisoformat(fetched_at_iso)
    age = datetime.now(timezone.utc) - fetched_at
    return age.total_seconds() > ttl_seconds


async def _fetchone(db, sql: str, params: tuple = ()) -> Any:
    cursor = await db.execute(sql, params)
    return await cursor.fetchone()


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

async def get_cached_bootstrap() -> dict[str, Any] | None:
    async with get_db() as db:
        row = await _fetchone(
            db, "SELECT data, fetched_at FROM bootstrap ORDER BY id DESC LIMIT 1"
        )
        if row is None:
            return None
        if _is_stale(row["fetched_at"], TTL_BOOTSTRAP_HOURS * 3600):
            return None
        return json.loads(row["data"])


async def set_cached_bootstrap(data: dict[str, Any]) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO bootstrap (data, fetched_at) VALUES (?, ?)",
            (json.dumps(data), _now_iso()),
        )
        await db.execute(
            "DELETE FROM bootstrap WHERE id NOT IN "
            "(SELECT id FROM bootstrap ORDER BY id DESC LIMIT 1)"
        )
        await db.commit()


async def get_stale_bootstrap() -> dict[str, Any] | None:
    """Return the most recent cached bootstrap regardless of age (fallback)."""
    async with get_db() as db:
        row = await _fetchone(
            db, "SELECT data FROM bootstrap ORDER BY id DESC LIMIT 1"
        )
        return json.loads(row["data"]) if row else None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

async def get_cached_fixtures() -> list[dict[str, Any]] | None:
    async with get_db() as db:
        row = await _fetchone(
            db, "SELECT data, fetched_at FROM fixtures ORDER BY id DESC LIMIT 1"
        )
        if row is None:
            return None
        if _is_stale(row["fetched_at"], TTL_FIXTURES_HOURS * 3600):
            return None
        return json.loads(row["data"])


async def set_cached_fixtures(data: list[dict[str, Any]]) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO fixtures (data, fetched_at) VALUES (?, ?)",
            (json.dumps(data), _now_iso()),
        )
        await db.execute(
            "DELETE FROM fixtures WHERE id NOT IN "
            "(SELECT id FROM fixtures ORDER BY id DESC LIMIT 1)"
        )
        await db.commit()


async def get_stale_fixtures() -> list[dict[str, Any]] | None:
    async with get_db() as db:
        row = await _fetchone(
            db, "SELECT data FROM fixtures ORDER BY id DESC LIMIT 1"
        )
        return json.loads(row["data"]) if row else None


# ---------------------------------------------------------------------------
# Squad
# ---------------------------------------------------------------------------

async def get_cached_squad(team_id: int, gameweek: int) -> dict[str, Any] | None:
    async with get_db() as db:
        row = await _fetchone(
            db,
            "SELECT data, fetched_at FROM squad "
            "WHERE team_id = ? AND gameweek = ? "
            "ORDER BY id DESC LIMIT 1",
            (team_id, gameweek),
        )
        if row is None:
            return None
        if _is_stale(row["fetched_at"], TTL_SQUAD_HOURS * 3600):
            return None
        return json.loads(row["data"])


async def set_cached_squad(team_id: int, gameweek: int, data: dict[str, Any]) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO squad (team_id, gameweek, data, fetched_at) VALUES (?, ?, ?, ?)",
            (team_id, gameweek, json.dumps(data), _now_iso()),
        )
        await db.execute(
            "DELETE FROM squad WHERE team_id = ? AND gameweek = ? AND id NOT IN "
            "(SELECT id FROM squad WHERE team_id = ? AND gameweek = ? "
            "ORDER BY id DESC LIMIT 1)",
            (team_id, gameweek, team_id, gameweek),
        )
        await db.commit()


async def get_stale_squad(team_id: int, gameweek: int) -> dict[str, Any] | None:
    async with get_db() as db:
        row = await _fetchone(
            db,
            "SELECT data FROM squad WHERE team_id = ? AND gameweek = ? "
            "ORDER BY id DESC LIMIT 1",
            (team_id, gameweek),
        )
        return json.loads(row["data"]) if row else None


# ---------------------------------------------------------------------------
# Player history
# ---------------------------------------------------------------------------

async def get_cached_player_history(player_id: int) -> dict[str, Any] | None:
    async with get_db() as db:
        row = await _fetchone(
            db,
            "SELECT data, fetched_at FROM player_history WHERE player_id = ?",
            (player_id,),
        )
        if row is None:
            return None
        if _is_stale(row["fetched_at"], TTL_PLAYER_HISTORY_HOURS * 3600):
            return None
        return json.loads(row["data"])


async def set_cached_player_history(player_id: int, data: dict[str, Any]) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT OR REPLACE INTO player_history (player_id, data, fetched_at) VALUES (?, ?, ?)",
            (player_id, json.dumps(data), _now_iso()),
        )
        await db.commit()


# ---------------------------------------------------------------------------
# Live scores
# ---------------------------------------------------------------------------

async def get_cached_live_scores(gameweek: int) -> dict[str, Any] | None:
    async with get_db() as db:
        row = await _fetchone(
            db,
            "SELECT data, fetched_at FROM live_scores WHERE gameweek = ?",
            (gameweek,),
        )
        if row is None:
            return None
        if _is_stale(row["fetched_at"], TTL_LIVE_SCORES_MINUTES * 60):
            return None
        return json.loads(row["data"])


async def set_cached_live_scores(gameweek: int, data: dict[str, Any]) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT OR REPLACE INTO live_scores (gameweek, data, fetched_at) VALUES (?, ?, ?)",
            (gameweek, json.dumps(data), _now_iso()),
        )
        await db.commit()


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

async def save_report(gameweek: int, content: str) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO reports (gameweek, content, created_at) VALUES (?, ?, ?)",
            (gameweek, content, _now_iso()),
        )
        await db.commit()


async def get_latest_report() -> dict[str, Any] | None:
    async with get_db() as db:
        row = await _fetchone(
            db,
            "SELECT gameweek, content, created_at FROM reports ORDER BY id DESC LIMIT 1",
        )
        if row is None:
            return None
        return {
            "gameweek": row["gameweek"],
            "content": row["content"],
            "created_at": row["created_at"],
        }


async def get_report_for_gameweek(gameweek: int) -> dict[str, Any] | None:
    async with get_db() as db:
        row = await _fetchone(
            db,
            "SELECT gameweek, content, created_at FROM reports "
            "WHERE gameweek = ? ORDER BY id DESC LIMIT 1",
            (gameweek,),
        )
        if row is None:
            return None
        return {
            "gameweek": row["gameweek"],
            "content": row["content"],
            "created_at": row["created_at"],
        }
