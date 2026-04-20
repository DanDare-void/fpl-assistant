"""
Claude-powered transfer and captain planner.

Takes enriched FPL context + the user's current squad (with selling prices)
and returns structured recommendations ready for the confirm UI.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic

from .client import ClaudeClient, REPORT_MODEL

logger = logging.getLogger(__name__)

PLANNER_MAX_TOKENS = 2048

PLANNER_SYSTEM_PROMPT = """\
You are an expert FPL analyst. Given a manager's current squad, their budget, \
and enriched player data, produce a structured set of recommendations for the \
upcoming gameweek.

You MUST respond with valid JSON only — no prose, no markdown fences. \
The JSON must match this exact schema:

{
  "captain": {
    "player_id": <int>,
    "player_name": "<str>",
    "reasoning": "<1-2 sentences>"
  },
  "vice_captain": {
    "player_id": <int>,
    "player_name": "<str>",
    "reasoning": "<1 sentence>"
  },
  "transfers": [
    {
      "out_player_id": <int>,
      "out_player_name": "<str>",
      "in_player_id": <int>,
      "in_player_name": "<str>",
      "reasoning": "<2-3 sentences covering form, fixtures, value>",
      "cost_hits": <int>
    }
  ],
  "chip": {
    "name": "<chip_name or null>",
    "reasoning": "<str or null>"
  },
  "summary": "<3-4 sentence overall summary>"
}

Rules:
- You may recommend up to the number of free transfers available (provided in the prompt). Never recommend more than free_transfers transfers unless a points hit is clearly worth it.
- If recommending more transfers than free_transfers, set cost_hits to 4 per extra transfer and justify the hit in the reasoning.
- Only recommend transfers that are within budget (bank + selling price >= purchase price).
- transfers array can be empty if no transfers are worthwhile.
- cost_hits: 0 if within free transfers, otherwise 4 per additional transfer.
- chip name must be one of: "wildcard", "freehit", "bboost", "3xc", or null.
- Only recommend a chip if there is a strong case for it this specific week.
- player_id values must exactly match the IDs in the data provided.
"""


async def generate_recommendations(
    fpl_context: dict[str, Any],
    my_team: dict[str, Any],
    free_transfers: int,
) -> dict[str, Any]:
    """
    Ask Claude to generate transfer + captain recommendations.

    Args:
        fpl_context: Enriched FPL context (from claude/context.py).
        my_team: Authenticated my-team response (includes selling prices).
        free_transfers: Number of free transfers available this week.

    Returns:
        Parsed recommendation dict matching the schema above.
    """
    prompt = (
        f"Free transfers available: {free_transfers}\n\n"
        f"My team (with selling prices):\n"
        f"```json\n{json.dumps(my_team, indent=2)}\n```\n\n"
        f"FPL context (player data, fixtures, transfer targets):\n"
        f"```json\n{json.dumps(fpl_context, indent=2)}\n```\n\n"
        "Generate recommendations as JSON."
    )

    import os
    client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    try:
        response = await client.messages.create(
            model=REPORT_MODEL,
            max_tokens=PLANNER_MAX_TOKENS,
            system=PLANNER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()

        # Strip markdown code fences if Claude added them despite instructions
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        return json.loads(raw)

    except json.JSONDecodeError as exc:
        logger.error("Claude returned invalid JSON for recommendations: %s", exc)
        raise RuntimeError("Failed to parse Claude recommendations") from exc
    except anthropic.APIStatusError as exc:
        raise RuntimeError(f"Claude API error: {exc.status_code}") from exc
