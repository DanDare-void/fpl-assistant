from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter

router = APIRouter()


@router.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "team_id": os.getenv("FPL_TEAM_ID"),
        "league_id": os.getenv("FPL_LEAGUE_ID"),
    }
