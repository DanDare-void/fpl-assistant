"""
POST /api/chat — SSE streaming chat endpoint.

Accepts a conversation history, injects FPL context into the system prompt,
and streams Claude's response back as Server-Sent Events.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..claude.client import ClaudeClient
from ..claude.context import build_context
from ..claude.prompts import build_chat_system_prompt
from ..fpl.client import FPLClient, FPLClientError
from ..fpl.enrichment import enrich_players
from ..fpl import cache

logger = logging.getLogger(__name__)
router = APIRouter()


class Message(BaseModel):
    role: str   # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]


def _team_id() -> int | None:
    val = os.getenv("FPL_TEAM_ID")
    return int(val) if val else None


async def _build_fpl_context() -> dict[str, Any]:
    """Fetch/cache FPL data and build the Claude context dict."""
    from ..fpl.models import Bootstrap, Fixture, Squad

    async with FPLClient() as client:
        # Bootstrap
        cached_bs = await cache.get_cached_bootstrap()
        if cached_bs:
            bootstrap = Bootstrap.model_validate(cached_bs)
        else:
            try:
                bootstrap = await client.get_bootstrap()
                await cache.set_cached_bootstrap(bootstrap.model_dump())
            except FPLClientError:
                stale = await cache.get_stale_bootstrap()
                bootstrap = Bootstrap.model_validate(stale) if stale else None

        # Fixtures
        cached_fx = await cache.get_cached_fixtures()
        if cached_fx:
            fixtures = [Fixture.model_validate(f) for f in cached_fx]
        else:
            try:
                fixtures = await client.get_fixtures()
                await cache.set_cached_fixtures([f.model_dump() for f in fixtures])
            except FPLClientError:
                stale = await cache.get_stale_fixtures()
                fixtures = [Fixture.model_validate(f) for f in stale] if stale else []

        # Squad (optional)
        squad = None
        team_id = _team_id()
        if bootstrap and team_id:
            current_gw = next(
                (gw.id for gw in bootstrap.events if gw.is_current),
                next((gw.id for gw in bootstrap.events if gw.is_next), 1),
            )
            cached_sq = await cache.get_cached_squad(team_id, current_gw)
            if cached_sq:
                squad = Squad.model_validate(cached_sq)
            else:
                try:
                    squad = await client.get_squad(team_id, current_gw)
                    await cache.set_cached_squad(team_id, current_gw, squad.model_dump())
                except FPLClientError as exc:
                    logger.warning("Could not fetch squad for chat context: %s", exc)
                    stale = await cache.get_stale_squad(team_id, current_gw)
                    if stale:
                        squad = Squad.model_validate(stale)

    if bootstrap is None:
        return {"error": "FPL data unavailable"}

    enriched = enrich_players(bootstrap, fixtures)
    return build_context(bootstrap, fixtures, squad, enriched_players=enriched)


async def _sse_stream(
    system_prompt: str,
    messages: list[dict[str, Any]],
) -> AsyncIterator[str]:
    claude = ClaudeClient()
    async for chunk in claude.stream_chat(system_prompt, messages):
        # Escape newlines in SSE data field
        escaped = chunk.replace("\n", "\\n")
        yield f"data: {escaped}\n\n"
    yield "data: [DONE]\n\n"


@router.post("/api/chat")
async def chat(request: ChatRequest) -> StreamingResponse:
    if not request.messages:
        raise HTTPException(status_code=400, detail="messages must not be empty")

    # Validate roles
    for msg in request.messages:
        if msg.role not in ("user", "assistant"):
            raise HTTPException(
                status_code=400, detail=f"Invalid message role: {msg.role}"
            )

    fpl_context = await _build_fpl_context()
    system_prompt = build_chat_system_prompt(fpl_context)

    messages = [{"role": m.role, "content": m.content} for m in request.messages]

    return StreamingResponse(
        _sse_stream(system_prompt, messages),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
