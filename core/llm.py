"""
core/llm.py

Singleton Anthropic client. Created once, shared across reshape, retrieve,
generate, and judge. Stops the pipeline from creating 4+ separate clients
per request.

The SDK's built-in retry handles transient API errors (429, 500, 503).
"""

from __future__ import annotations

import anthropic

_async_client: anthropic.AsyncAnthropic | None = None


def get_anthropic() -> anthropic.AsyncAnthropic:
    """Return the shared AsyncAnthropic client, creating it on first call.

    The client is configured with max_retries=3 for automatic retry on
    transient errors (rate limits, server errors).
    """
    global _async_client
    if _async_client is None:
        _async_client = anthropic.AsyncAnthropic(max_retries=3)
    return _async_client
