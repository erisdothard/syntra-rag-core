"""
core/query/reshape.py — LIVE

Rewrite the user's question to improve retrieval quality.

Two operations:
  1. Vocabulary injection — expand the question with domain-specific terms
     from the client config so vector search hits the right embeddings.
  2. Query decomposition — if the question is compound, break it into
     sub-queries for independent retrieval.

The reshaper is industry-neutral. The vocabulary hints come from the client's
config.yaml, injected at call time. The core never knows what the terms mean.

Build order: Step 7.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from core.llm import get_anthropic

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReshapedQuery:
    """Output of the reshape step."""

    original: str
    rewritten: str
    sub_queries: list[str]  # empty if the question didn't decompose


_RESHAPE_PROMPT = """
You are a query rewriter for a retrieval system. Your job is to improve the
user's question so it retrieves the most relevant documents.

You have these domain vocabulary hints: {vocabulary}

Given the user's question, do TWO things:

1. REWRITE the question to be more specific, incorporating relevant vocabulary
   terms where appropriate. Keep the original intent. Do not answer the question.

2. If the question asks about multiple distinct things, DECOMPOSE it into
   independent sub-queries (max 3). If it's a single focused question, return
   an empty list.

Respond with ONLY a JSON object:
{{
    "rewritten": "the improved question",
    "sub_queries": ["sub-query 1", "sub-query 2"] or []
}}

User question: {question}
""".strip()


async def reshape(
    question: str,
    *,
    vocabulary_hints: list[str],
    model: str = "claude-haiku-4-5-20251001",
) -> ReshapedQuery:
    """Reshape a user question for better retrieval.

    Args:
        question:          Raw user question.
        vocabulary_hints:  Domain terms from client config.
        model:             Anthropic model for rewriting.

    Returns:
        ReshapedQuery with the rewritten question and any sub-queries.
    """
    if not question.strip():
        return ReshapedQuery(original=question, rewritten=question, sub_queries=[])

    vocab_str = ", ".join(vocabulary_hints) if vocabulary_hints else "(none provided)"

    prompt = _RESHAPE_PROMPT.format(
        vocabulary=vocab_str,
        question=question,
    )

    client = get_anthropic()

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=512,
            temperature=0.0,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text
        parsed = _parse_response(raw)

        result = ReshapedQuery(
            original=question,
            rewritten=parsed.get("rewritten", question),
            sub_queries=parsed.get("sub_queries", []),
        )

        logger.info(
            "Reshaped query: '%s' → '%s' (%d sub-queries)",
            question[:80],
            result.rewritten[:80],
            len(result.sub_queries),
        )
        return result

    except Exception:
        logger.exception("Reshape failed — using original question")
        return ReshapedQuery(original=question, rewritten=question, sub_queries=[])


def _parse_response(raw: str) -> dict:
    """Parse the reshaper's JSON response."""
    import json

    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        cleaned = "\n".join(lines[1:-1]).strip()

    try:
        result = json.loads(cleaned)
        if isinstance(result, dict):
            # Validate sub_queries is a list of strings
            subs = result.get("sub_queries", [])
            if not isinstance(subs, list):
                result["sub_queries"] = []
            else:
                result["sub_queries"] = [s for s in subs if isinstance(s, str) and s.strip()]
            return result
    except json.JSONDecodeError:
        logger.warning("Unparseable reshape response: %s", raw[:200])

    return {}
