"""
Admin routes — token usage stats.
"""

from __future__ import annotations

from fastapi import APIRouter

from ..db import get_db

router = APIRouter()

# Pricing in USD per million tokens (as of 2025)
PRICING = {
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00, "cache_read": 0.08, "cache_write": 1.00},
    "claude-sonnet-4-6":         {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_write": 3.75},
}


def _cost(model: str, input_t: int, output_t: int, cache_read: int, cache_write: int) -> float:
    p = PRICING.get(model, {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_write": 3.75})
    return (
        input_t * p["input"]
        + output_t * p["output"]
        + cache_read * p["cache_read"]
        + cache_write * p["cache_write"]
    ) / 1_000_000


@router.get("/api/admin/usage")
async def get_usage() -> dict:
    async with get_db() as db:
        # Totals by call type
        cursor = await db.execute("""
            SELECT
                call_type,
                model,
                COUNT(*)            AS calls,
                SUM(input_tokens)   AS input_tokens,
                SUM(output_tokens)  AS output_tokens,
                SUM(cache_read)     AS cache_read,
                SUM(cache_write)    AS cache_write
            FROM token_usage
            GROUP BY call_type, model
            ORDER BY call_type
        """)
        rows = await cursor.fetchall()

        by_type = []
        grand_cost = 0.0
        grand_input = grand_output = 0
        for row in rows:
            cost = _cost(row["model"], row["input_tokens"], row["output_tokens"],
                         row["cache_read"], row["cache_write"])
            grand_cost += cost
            grand_input += row["input_tokens"]
            grand_output += row["output_tokens"]
            by_type.append({
                "call_type": row["call_type"],
                "model": row["model"],
                "calls": row["calls"],
                "input_tokens": row["input_tokens"],
                "output_tokens": row["output_tokens"],
                "cache_read": row["cache_read"],
                "cache_write": row["cache_write"],
                "estimated_cost_usd": round(cost, 4),
            })

        # Recent calls (last 20)
        cursor = await db.execute("""
            SELECT created_at, call_type, model, input_tokens, output_tokens, cache_read, cache_write
            FROM token_usage
            ORDER BY id DESC
            LIMIT 20
        """)
        recent_rows = await cursor.fetchall()
        recent = [
            {
                "created_at": r["created_at"],
                "call_type": r["call_type"],
                "model": r["model"],
                "input_tokens": r["input_tokens"],
                "output_tokens": r["output_tokens"],
                "cache_read": r["cache_read"],
                "cache_write": r["cache_write"],
                "estimated_cost_usd": round(
                    _cost(r["model"], r["input_tokens"], r["output_tokens"],
                          r["cache_read"], r["cache_write"]), 4
                ),
            }
            for r in recent_rows
        ]

    return {
        "by_type": by_type,
        "recent": recent,
        "totals": {
            "input_tokens": grand_input,
            "output_tokens": grand_output,
            "estimated_cost_usd": round(grand_cost, 4),
        },
    }
