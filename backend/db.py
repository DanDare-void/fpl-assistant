import logging
import os
import aiosqlite
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)

DATABASE_PATH = os.getenv("DATABASE_PATH", "./data/fpl.db")


@asynccontextmanager
async def get_db() -> AsyncIterator[aiosqlite.Connection]:
    Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db


async def init_db() -> None:
    Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS cache_meta (
                key     TEXT PRIMARY KEY,
                fetched_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS bootstrap (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                data        TEXT NOT NULL,
                fetched_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS fixtures (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                data        TEXT NOT NULL,
                fetched_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS squad (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id     INTEGER NOT NULL,
                gameweek    INTEGER NOT NULL,
                data        TEXT NOT NULL,
                fetched_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS player_history (
                player_id   INTEGER PRIMARY KEY,
                data        TEXT NOT NULL,
                fetched_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS live_scores (
                gameweek    INTEGER PRIMARY KEY,
                data        TEXT NOT NULL,
                fetched_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS reports (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                gameweek    INTEGER NOT NULL,
                content     TEXT NOT NULL,
                created_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS token_usage (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                call_type       TEXT NOT NULL,
                model           TEXT NOT NULL,
                input_tokens    INTEGER NOT NULL,
                output_tokens   INTEGER NOT NULL,
                cache_read      INTEGER NOT NULL DEFAULT 0,
                cache_write     INTEGER NOT NULL DEFAULT 0
            );
        """)
        await db.commit()


async def log_token_usage(
    call_type: str,
    model: str,
    usage: Any,
) -> None:
    """Record Claude API token usage. usage is the anthropic Usage object."""
    try:
        async with get_db() as db:
            await db.execute(
                """
                INSERT INTO token_usage (call_type, model, input_tokens, output_tokens, cache_read, cache_write)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    call_type,
                    model,
                    getattr(usage, "input_tokens", 0),
                    getattr(usage, "output_tokens", 0),
                    getattr(usage, "cache_read_input_tokens", 0),
                    getattr(usage, "cache_creation_input_tokens", 0),
                ),
            )
            await db.commit()
    except Exception as exc:
        logger.warning("Failed to log token usage: %s", exc)
