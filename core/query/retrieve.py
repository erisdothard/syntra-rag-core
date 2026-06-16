"""
core/query/retrieve.py — LIVE

Hybrid search: pgvector cosine similarity + Postgres full-text search in
one system, then rerank the merged results. No second store.

Industry-neutral. The query and client name are the only inputs.
Domain meaning of results is the client's concern.

Build order: Step 6.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import anthropic

from core.db import get_supabase
from core.ingestion.index import embed_texts
from core.trust.validate import validate_retrieval

logger = logging.getLogger(__name__)


async def retrieve(
    query: str,
    *,
    client_name: str,
    top_k: int = 5,
    rerank: bool = True,
    rerank_top_k: int = 3,
    rerank_model: str = "claude-haiku-4-5-20251001",
    embed_model: str = "voyage-3",
) -> list[dict[str, Any]]:
    """Hybrid retrieve: vector + full-text search, optional LLM rerank.

    Args:
        query:          The user's question (already reshaped by reshape.py).
        client_name:    Client identifier for tenant filtering.
        top_k:          Number of candidates from hybrid search.
        rerank:         Whether to rerank with LLM.
        rerank_top_k:   Final number of results after reranking.
        rerank_model:   Anthropic model for reranking.
        embed_model:    Embedding model matching what was used at index time.

    Returns:
        List of chunk dicts with 'score' added, ordered best-first.
    """
    # Embed the query
    query_embeddings = await embed_texts([query], model=embed_model, input_type="query")
    query_vector = query_embeddings[0]

    # Run hybrid search
    candidates = await _hybrid_search(
        query_text=query,
        query_vector=query_vector,
        client_name=client_name,
        limit=top_k,
    )

    if not candidates:
        logger.warning("No candidates found for query: %s", query[:100])
        return []

    logger.info("Hybrid search returned %d candidates", len(candidates))

    if rerank and len(candidates) > 1:
        candidates = await _rerank(
            query=query,
            candidates=candidates,
            top_k=rerank_top_k,
            model=rerank_model,
        )
        logger.info("Reranked to %d results", len(candidates))

    # Validate retrieval result (cheap Pydantic check)
    total_candidates = top_k  # pre-rerank count
    validate_retrieval(
        query=query,
        chunks=candidates,
        total_candidates=total_candidates,
    )

    return candidates


# ---------------------------------------------------------------------------
# Hybrid search — vector + full-text in one query via Supabase RPC
# ---------------------------------------------------------------------------


async def _hybrid_search(
    *,
    query_text: str,
    query_vector: list[float],
    client_name: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Execute hybrid search using a Supabase RPC function.

    Expects a Postgres function `hybrid_search` to be defined:

    ```sql
    create or replace function hybrid_search(
        query_text text,
        query_embedding vector(1024),
        match_client text,
        match_limit int default 10,
        vector_weight float default 0.7,
        fts_weight float default 0.3
    ) returns table (
        id uuid,
        client text,
        domain_key text,
        kind text,
        variant text,
        content text,
        metadata jsonb,
        score float
    ) language plpgsql as $$
    begin
        return query
        select
            c.id, c.client, c.domain_key, c.kind, c.variant,
            c.content, c.metadata,
            (
                vector_weight * (1 - (c.embedding <=> query_embedding)) +
                fts_weight * coalesce(ts_rank(
                    to_tsvector('english', c.content),
                    plainto_tsquery('english', query_text)
                ), 0)
            ) as score
        from chunks c
        where c.client = match_client
        order by score desc
        limit match_limit;
    end;
    $$;
    ```
    """
    supabase = get_supabase()

    result = supabase.rpc(
        "hybrid_search",
        {
            "query_text": query_text,
            "query_embedding": query_vector,
            "match_client": client_name,
            "match_limit": limit,
        },
    ).execute()

    return result.data or []


# ---------------------------------------------------------------------------
# Rerank — LLM-based relevance reranking
# ---------------------------------------------------------------------------


async def _rerank(
    *,
    query: str,
    candidates: list[dict[str, Any]],
    top_k: int,
    model: str,
) -> list[dict[str, Any]]:
    """Rerank candidates using an LLM to judge relevance.

    Sends the query + candidate contents to the model and asks it to
    rank them by relevance. Returns the top_k best.
    """
    # Build numbered list for the LLM
    numbered = []
    for i, c in enumerate(candidates):
        numbered.append(f"[{i}] {c.get('content', '')[:500]}")

    prompt = (
        f"Given this question:\n\n{query}\n\n"
        f"Rank these {len(candidates)} passages by relevance to the question. "
        f"Return ONLY a JSON array of passage indices in order from most to least "
        f"relevant. Example: [2, 0, 4, 1, 3]\n\n"
        + "\n\n".join(numbered)
    )

    client = anthropic.AsyncAnthropic()

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=256,
            temperature=0.0,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text
        ranking = _parse_ranking(raw, len(candidates))
    except Exception:
        logger.exception("Rerank failed — returning original order")
        ranking = list(range(len(candidates)))

    # Reorder and assign new scores
    reranked = []
    for rank, idx in enumerate(ranking[:top_k]):
        if 0 <= idx < len(candidates):
            entry = dict(candidates[idx])
            entry["score"] = 1.0 - (rank / len(ranking))  # linear decay
            reranked.append(entry)

    return reranked


def _parse_ranking(raw: str, n: int) -> list[int]:
    """Parse the LLM's ranking response into a list of indices."""
    import json

    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        cleaned = "\n".join(lines[1:-1]).strip()

    try:
        indices = json.loads(cleaned)
        if isinstance(indices, list) and all(isinstance(i, int) for i in indices):
            return indices
    except (json.JSONDecodeError, TypeError):
        pass

    logger.warning("Unparseable ranking response: %s", raw[:200])
    return list(range(n))


