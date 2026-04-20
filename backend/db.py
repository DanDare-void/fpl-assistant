import os
import aiosqlite
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

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
        """)
        await db.commit()
