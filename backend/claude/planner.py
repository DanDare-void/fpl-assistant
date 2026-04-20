"""
Claude-powered transfer and captain planner.

All budget numbers are pre-computed by the caller and passed in explicitly.
Claude's only job is to decide WHO to transfer and WHY — zero arithmetic.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import anthropic

from ..db import log_token_usage

logger = logging.getLogger(__name__)

PLANNER_MODEL = "claude-sonnet-4-6"
PLANNER_MAX_TOKENS = 8192

PLANNER_SYSTEM_PROMPT = """\
You are an expert FPL analyst. You will be given:
- A manager's current squad with exact selling prices
- Their bank balance in millions
- A ranked list of transfer options, each with exact net cost pre-computed

Your job: select transfers greedily from the ranked list, then pick a captain.

TRANSFER SELECTION ALGORITHM (follow exactly):
1. Start with running_budget = bank_millions
2. Work through ranked_transfer_options from rank 1 downward (highest impact first)
3. For each option: check if (running_budget + out_selling_price_millions - in_cost_millions) >= 0
   - If YES: select this transfer, update running_budget += out_selling_price_millions - in_cost_millions, continue
   - If NO: skip this option, keep looking for one that fits
4. Stop when you have used all free_transfers (additional transfers cost 4 points each — only take a hit if clearly worthwhile)
5. Do NOT invent players. Do NOT invent prices. Use ONLY the exact values from the lists provided.
6. net_cost_millions is pre-computed and exact — do not recalculate it.

You MUST respond with valid JSON only — no prose, no markdown fences.
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
      "out_selling_price_millions": <float>,
      "in_player_id": <int>,
      "in_player_name": "<str>",
      "in_cost_millions": <float>,
      "reasoning": "<2-3 sentences: form, fixtures, value>"
    }
  ],
  "budget_check": {
    "bank_millions": <float>,
    "total_sold_millions": <float>,
    "total_bought_millions": <float>,
    "remaining_bank_millions": <float>
  },
  "chip": {
    "name": "<chip_name or null>",
    "reasoning": "<str or null>"
  },
  "summary": "<3-4 sentence overall summary of your decisions>"
}

Additional rules:
- captain and vice_captain MUST be players currently in current_squad.
- transfers may be [] if no moves are worthwhile.
- chip name must be one of: "wildcard", "freehit", "bboost", "3xc", or null.
- budget_check: fill in with the exact values from your selected transfers.
  total_sold_millions = sum of out_selling_price_millions for selected transfers.
  total_bought_millions = sum of in_cost_millions for selected transfers.
  remaining_bank_millions = bank_millions + total_sold_millions - total_bought_millions.
- This must satisfy: remaining_bank_millions >= 0. If it does not, remove the last transfer.
"""


SQUAD_BUILDER_SYSTEM_PROMPT = """\
You are an expert FPL team builder. Given a budget and candidate players per position, \
build the optimal 15-player FPL squad.

SQUAD REQUIREMENTS (non-negotiable):
- Exactly 2 Goalkeepers (GKP)
- Exactly 5 Defenders (DEF)
- Exactly 5 Midfielders (MID)
- Exactly 3 Forwards (FWD)
- Maximum 3 players from any single club
- Total cost <= budget_millions (use exact costs provided — do not estimate)

STARTING XI (11 players): 1 GKP + 10 outfield in a valid formation (e.g. 4-4-2, 4-3-3, 3-4-3, 3-5-2, 5-4-1 — min 3 DEF, min 2 MID, min 1 FWD)
BENCH (4 players): Budget picks for the remaining slots (1 GKP + 3 outfield)

SELECTION STRATEGY:
1. Prioritise players with high form, good upcoming fixtures (low avg_fdr_3gw), and consistent minutes.
2. Balance 2-3 premium picks (£9m+) with solid mid-rangers and cheap bench fillers.
3. Keep club counts <= 3 — check this carefully.
4. Total cost must be <= budget_millions — verify before finalising.

You MUST respond with valid JSON only — no prose, no markdown fences.
Schema:

{
  "squad": [
    {
      "player_id": <int>,
      "name": "<str>",
      "team": "<str>",
      "position": "<GKP|DEF|MID|FWD>",
      "cost_millions": <float>,
      "is_starter": <bool>,
      "reasoning": "<1 sentence>"
    }
  ],
  "captain_id": <int>,
  "vice_captain_id": <int>,
  "formation": "<str e.g. 4-4-2>",
  "total_cost_millions": <float>,
  "remaining_budget_millions": <float>,
  "summary": "<3-4 sentences on your selections, premiums chosen, and budget approach>"
}

Verify before responding:
- Exactly 2 GKP, 5 DEF, 5 MID, 3 FWD in squad (15 total)
- No club appears more than 3 times
- total_cost_millions <= budget_millions
- remaining_budget_millions = budget_millions - total_cost_millions
"""


async def generate_squad(
    budget_millions: float,
    candidates: dict[str, list[dict]],
) -> dict:
    """
    Ask Claude to build a 15-player squad from scratch within a given budget.

    Args:
        budget_millions: Total squad budget (100.0 for new team / free hit).
        candidates: Dict of position -> list of candidate player dicts.

    Returns:
        Parsed squad recommendation dict.
    """
    prompt = (
        f"Budget: £{budget_millions}m\n\n"
        f"Player candidates by position (sorted by composite score — best first):\n"
        f"```json\n{json.dumps(candidates, indent=2)}\n```\n\n"
        "Build the best 15-player squad within the budget. "
        "Check club counts (max 3 per club) and position quotas carefully. "
        "Output the JSON object only."
    )

    client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    try:
        response = await client.messages.create(
            model=PLANNER_MODEL,
            max_tokens=PLANNER_MAX_TOKENS,
            system=SQUAD_BUILDER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        logger.info("Squad builder stop_reason=%s", response.stop_reason)
        await log_token_usage("squad_builder", PLANNER_MODEL, response.usage)
        raw = response.content[0].text.strip()
        logger.info("Squad builder raw (%d chars): %.300r", len(raw), raw)

        if not raw:
            raise RuntimeError(f"Claude returned empty response (stop_reason={response.stop_reason})")

        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        if not raw.startswith("{"):
            start = raw.find("{")
            end = raw.rfind("}")
            if start == -1 or end == -1:
                raise RuntimeError("Claude did not return a JSON object for squad builder.")
            raw = raw[start:end + 1]

        result = json.loads(raw)

        # Server-side verify total cost
        if "squad" in result:
            actual_total = sum(p.get("cost_millions", 0) for p in result["squad"])
            result["total_cost_millions"] = round(actual_total, 1)
            result["remaining_budget_millions"] = round(budget_millions - actual_total, 1)
            if actual_total > budget_millions + 0.05:
                result["_budget_warning"] = (
                    f"Squad costs £{actual_total:.1f}m which exceeds the £{budget_millions:.1f}m budget."
                )

        return result

    except json.JSONDecodeError as exc:
        logger.error("Claude returned invalid JSON for squad builder: %s", exc)
        raise RuntimeError("Failed to parse Claude squad recommendation") from exc
    except anthropic.APIStatusError as exc:
        raise RuntimeError(f"Claude API error: {exc.status_code}") from exc


async def generate_recommendations(
    planning_data: dict[str, Any],
    free_transfers: int,
) -> dict[str, Any]:
    """
    Ask Claude to generate transfer + captain recommendations.

    Args:
        planning_data: Pre-computed budget info, squad with selling prices,
                       and ranked transfer options. All numbers verified.
        free_transfers: Number of free transfers available.

    Returns:
        Parsed recommendation dict matching the schema above.
    """
    prompt = (
        f"Free transfers available at zero cost: {free_transfers}\n\n"
        f"Planning data (all prices exact — use them verbatim, do not recalculate):\n"
        f"```json\n{json.dumps(planning_data, indent=2)}\n```\n\n"
        "Output the JSON object directly. Do not explain your reasoning, do not use markdown. "
        "Select transfers greedily from ranked_transfer_options (highest impact_score first): "
        "accumulate running_budget = bank + sum(out prices) - sum(in prices); include a transfer only if running_budget >= 0 after it. "
        "Use exact prices from the data — never estimate or recalculate."
    )

    client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    try:
        response = await client.messages.create(
            model=PLANNER_MODEL,
            max_tokens=PLANNER_MAX_TOKENS,
            system=PLANNER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        logger.info("Claude stop_reason=%s content_blocks=%d", response.stop_reason, len(response.content))
        await log_token_usage("planner", PLANNER_MODEL, response.usage)
        raw = response.content[0].text.strip()
        logger.info("Claude raw response (%d chars): %.300r", len(raw), raw)

        if not raw:
            raise RuntimeError(f"Claude returned an empty response (stop_reason={response.stop_reason}). Try again.")

        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        # If Claude wrote prose before the JSON, find the first { and last }
        if not raw.startswith("{"):
            start = raw.find("{")
            end = raw.rfind("}")
            if start == -1 or end == -1:
                logger.error("No JSON object found in Claude response: %.500r", raw)
                raise RuntimeError("Claude did not return a JSON object in its response.")
            raw = raw[start:end + 1]

        result = json.loads(raw)

        # Server-side verify Claude's budget_check arithmetic
        if "budget_check" in result and "transfers" in result:
            bc = result["budget_check"]
            total_sold = sum(t.get("out_selling_price_millions", 0) for t in result["transfers"])
            total_bought = sum(t.get("in_cost_millions", 0) for t in result["transfers"])
            bank = planning_data.get("bank_millions", 0)
            remaining = round(bank + total_sold - total_bought, 1)

            # Correct budget_check with actual arithmetic regardless of what Claude said
            result["budget_check"] = {
                "bank_millions": bank,
                "total_sold_millions": round(total_sold, 1),
                "total_bought_millions": round(total_bought, 1),
                "remaining_bank_millions": remaining,
            }

            if remaining < 0:
                logger.warning(
                    "Claude produced unaffordable transfers: bought=£%.1fm sold=£%.1fm bank=£%.1fm remaining=£%.1fm",
                    total_bought, total_sold, bank, remaining,
                )
                result["_budget_warning"] = (
                    f"Claude's recommendations exceed budget by "
                    f"£{abs(remaining):.1f}m — review before confirming."
                )

        return result

    except json.JSONDecodeError as exc:
        logger.error("Claude returned invalid JSON for recommendations: %s", exc)
        raise RuntimeError("Failed to parse Claude recommendations") from exc
    except anthropic.APIStatusError as exc:
        raise RuntimeError(f"Claude API error: {exc.status_code}") from exc
