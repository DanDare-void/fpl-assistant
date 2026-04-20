"""
FPL Assistant — FastAPI application entrypoint.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

load_dotenv()

from .db import init_db
from .routes.health import router as health_router
from .routes.squad import router as squad_router
from .routes.chat import router as chat_router
from .routes.report import router as report_router
from .routes.auth import router as auth_router
from .routes.manage import router as manage_router
from .routes.admin import router as admin_router


# ---------------------------------------------------------------------------
# Logging setup — rotating file log + console
# ---------------------------------------------------------------------------

def setup_logging() -> None:
    log_dir = Path("./logs")
    log_dir.mkdir(exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s — %(message)s")

    # Console handler
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    # Rotating file handler (max 10MB, keep 3 backups)
    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "fpl-assistant.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=3,
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)


setup_logging()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting FPL Assistant")
    await init_db()

    # Prime the cache on startup (best-effort)
    try:
        from .fpl.client import FPLClient
        from .fpl import cache

        async with FPLClient() as client:
            cached_bs = await cache.get_cached_bootstrap()
            if cached_bs is None:
                logger.info("Priming bootstrap cache on startup...")
                bootstrap = await client.get_bootstrap()
                await cache.set_cached_bootstrap(bootstrap.model_dump())

            cached_fx = await cache.get_cached_fixtures()
            if cached_fx is None:
                logger.info("Priming fixtures cache on startup...")
                fixtures = await client.get_fixtures()
                await cache.set_cached_fixtures([f.model_dump() for f in fixtures])

        logger.info("Cache primed successfully")
    except Exception as exc:
        logger.warning("Cache priming failed (will retry on first request): %s", exc)

    yield

    logger.info("Shutting down FPL Assistant")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="FPL Assistant",
    description="AI-powered Fantasy Premier League assistant",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow frontend dev server (Vite default :5173)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        os.getenv("FRONTEND_ORIGIN", ""),
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(health_router)
app.include_router(squad_router)
app.include_router(chat_router)
app.include_router(report_router)
app.include_router(auth_router)
app.include_router(manage_router)
app.include_router(admin_router)

# Serve built frontend — only if dist/ exists (skipped in dev)
DIST_DIR = Path("frontend/dist")
if DIST_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(DIST_DIR), html=True), name="frontend")
