"""
Anthropic API client — streaming chat and one-shot report generation.
"""

from __future__ import annotations

import logging
import os
from typing import Any, AsyncIterator

import anthropic

from ..db import log_token_usage

logger = logging.getLogger(__name__)

CHAT_MODEL = "claude-haiku-4-5-20251001"
REPORT_MODEL = "claude-sonnet-4-6"

CHAT_MAX_TOKENS = 1024
REPORT_MAX_TOKENS = 2048


class ClaudeClient:
    def __init__(self) -> None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY environment variable not set")
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def stream_chat(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
    ) -> AsyncIterator[str]:
        """
        Stream a chat response as text chunks.
        Yields raw text strings — caller wraps in SSE format.
        """
        try:
            async with self._client.messages.stream(
                model=CHAT_MODEL,
                max_tokens=CHAT_MAX_TOKENS,
                system=system_prompt,
                messages=messages,
            ) as stream:
                async for text in stream.text_stream:
                    yield text
                final = await stream.get_final_message()
                await log_token_usage("chat", CHAT_MODEL, final.usage)
        except anthropic.APIStatusError as exc:
            logger.error("Anthropic API error during chat: %s", exc)
            yield f"\n\n[Error: Claude API returned {exc.status_code}. Please try again.]"
        except anthropic.APIConnectionError as exc:
            logger.error("Anthropic connection error during chat: %s", exc)
            yield "\n\n[Error: Could not reach Claude API. Check your connection.]"

    async def generate_report(
        self,
        system_prompt: str,
        context_message: str,
    ) -> str:
        """
        Generate a full weekly report (non-streaming).
        Returns the complete response text.
        """
        try:
            response = await self._client.messages.create(
                model=REPORT_MODEL,
                max_tokens=REPORT_MAX_TOKENS,
                system=system_prompt,
                messages=[{"role": "user", "content": context_message}],
            )
            await log_token_usage("report", REPORT_MODEL, response.usage)
            return response.content[0].text
        except anthropic.APIStatusError as exc:
            logger.error("Anthropic API error during report generation: %s", exc)
            raise RuntimeError(f"Claude API error: {exc.status_code}") from exc
        except anthropic.APIConnectionError as exc:
            logger.error("Anthropic connection error during report: %s", exc)
            raise RuntimeError("Could not reach Claude API") from exc
