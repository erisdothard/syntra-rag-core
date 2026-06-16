"""
core/query/generate.py — LIVE

Claude call with retrieved context. Assembles the system prompt (from client),
the evidence chunks, and the user question into a single generation request.

Returns a validated GenerationResult. Every answer flows through the trust
layer's validate.py before leaving this module.

Build order: Step 8.
"""

from __future__ import annotations

import logging
from typing import Any

import anthropic

from core.trust.validate import (
    GenerationResult,
    RetrievedChunk,
    TokenUsage,
    validate_generation,
)

logger = logging.getLogger(__name__)


async def generate(
    *,
    query: str,
    chunks: list[dict[str, Any]],
    system_prompt: str,
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 2048,
    temperature: float = 0.0,
) -> GenerationResult:
    """Generate an answer grounded in retrieved chunks.

    Args:
        query:          The user's question (reshaped).
        chunks:         Retrieved chunk dicts (from retrieve.py).
        system_prompt:  Client's system prompt (from prompt.md).
        model:          Anthropic model ID for generation.
        max_tokens:     Max output tokens.
        temperature:    Sampling temperature.

    Returns:
        Validated GenerationResult.

    Raises:
        ValidationError: If the generated answer fails validation.
    """
    evidence_block = _format_evidence(chunks)

    user_message = (
        f"Evidence:\n\n{evidence_block}\n\n---\n\n"
        f"Question: {query}"
    )

    client = anthropic.AsyncAnthropic()

    response = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    answer = response.content[0].text
    usage = response.usage

    logger.info(
        "Generated %d chars, %d input / %d output tokens",
        len(answer),
        usage.input_tokens,
        usage.output_tokens,
    )

    # Validate through the trust layer
    return validate_generation(
        query=query,
        answer=answer,
        model=model,
        chunks_used=[
            {
                "domain_key": c.get("domain_key"),
                "kind": c.get("kind", "unknown"),
                "variant": c.get("variant"),
                "content": c.get("content", ""),
                "metadata": c.get("metadata", {}),
                "score": c.get("score", 0.0),
            }
            for c in chunks
        ],
        token_usage={
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
        },
    )


def _format_evidence(chunks: list[dict[str, Any]]) -> str:
    """Format retrieved chunks into a numbered evidence block for the prompt."""
    if not chunks:
        return "(No evidence retrieved.)"

    parts = []
    for i, chunk in enumerate(chunks, 1):
        content = chunk.get("content", "")
        score = chunk.get("score", 0.0)
        kind = chunk.get("kind", "unknown")
        domain_key = chunk.get("domain_key", "")

        header = f"[{i}] {kind}"
        if domain_key:
            header += f" — {domain_key}"
        header += f" (relevance: {score:.2f})"

        parts.append(f"{header}\n{content}")

    return "\n\n---\n\n".join(parts)
