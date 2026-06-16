"""
core/ingestion/index.py — OFFLINE

Embed chunks and upsert to Supabase pgvector. Generic schema.

Re-running must not duplicate rows. Dedup key comes from the client's
dedup_key() — stored in metadata and used for ON CONFLICT resolution.

Embedding provider is configurable. Default: Voyage AI (voyage-3, 1024 dims)
which is Anthropic's recommended embedding model.

Build order: Step 6.
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

import httpx
from pydantic import BaseModel

from core.db import get_supabase
from core.interfaces import Chunk

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

_DEFAULT_EMBED_MODEL = "voyage-3"
_DEFAULT_EMBED_DIM = 1024
_VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
_BATCH_SIZE = 32  # Max batch size (maximize tokens per request at 3 RPM)
_MAX_RETRIES = 10
_REQUEST_DELAY = 22.0  # 3 RPM limit without payment method = 1 req per 20s + buffer


async def embed_texts(
    texts: list[str],
    *,
    model: str = _DEFAULT_EMBED_MODEL,
    input_type: str = "document",
    api_key: str | None = None,
) -> list[list[float]]:
    """Embed a list of texts using Voyage AI.

    Args:
        texts:      Strings to embed.
        model:      Voyage AI model ID.
        input_type: "document" for indexing, "query" for retrieval.
                    Voyage AI optimizes embeddings differently for each.
        api_key:    Voyage AI API key. Falls back to VOYAGE_API_KEY env var.

    Returns:
        List of embedding vectors, same order as input.
    """
    import asyncio

    key = api_key or os.environ.get("VOYAGE_API_KEY", "")
    if not key:
        raise RuntimeError("VOYAGE_API_KEY not set")

    all_embeddings: list[list[float]] = []

    async with httpx.AsyncClient(timeout=120.0) as client:
        for i in range(0, len(texts), _BATCH_SIZE):
            batch = texts[i : i + _BATCH_SIZE]

            for attempt in range(_MAX_RETRIES):
                response = await client.post(
                    _VOYAGE_URL,
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "input": batch,
                        "model": model,
                        "input_type": input_type,
                    },
                )
                if response.status_code == 429:
                    wait = min(2 ** attempt + 1, 60)
                    logger.warning("Rate limited, waiting %ds (attempt %d/%d)", wait, attempt + 1, _MAX_RETRIES)
                    await asyncio.sleep(wait)
                    continue
                response.raise_for_status()
                break

            data = response.json()
            batch_embeddings = [item["embedding"] for item in data["data"]]
            all_embeddings.extend(batch_embeddings)
            logger.info("Embedded batch %d-%d / %d", i, i + len(batch), len(texts))

            # Throttle to stay under rate limits
            await asyncio.sleep(_REQUEST_DELAY)

    return all_embeddings


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------


async def index_chunks(
    chunks: list[Chunk],
    *,
    client_name: str,
    dedup_keys: list[str],
    embed_model: str = _DEFAULT_EMBED_MODEL,
) -> int:
    """Embed and upsert chunks to Supabase.

    Args:
        chunks:      Deduplicated Chunk list from ingestion.
        client_name: Client identifier (stored on every row for tenant isolation).
        dedup_keys:  Parallel list of dedup keys (from parser.dedup_key()).
        embed_model: Voyage AI model to use for embeddings.

    Returns:
        Number of rows upserted.
    """
    if not chunks:
        logger.info("No chunks to index")
        return 0

    if len(chunks) != len(dedup_keys):
        raise ValueError(
            f"chunks ({len(chunks)}) and dedup_keys ({len(dedup_keys)}) must be same length"
        )

    logger.info("Embedding %d chunks with %s", len(chunks), embed_model)
    texts = [c.content for c in chunks]
    embeddings = await embed_texts(texts, model=embed_model)

    rows = []
    for chunk, dedup_key, embedding in zip(chunks, dedup_keys, embeddings):
        # Deterministic UUID from dedup key + client for idempotent upserts
        row_id = _deterministic_id(client_name, dedup_key)
        rows.append({
            "id": row_id,
            "client": client_name,
            "domain_key": chunk.domain_key,
            "kind": chunk.kind,
            "variant": chunk.variant,
            "content": chunk.content,
            "metadata": chunk.metadata,
            "embedding": embedding,
        })

    supabase = get_supabase()

    # Upsert in batches to avoid payload limits
    upserted = 0
    batch_size = 100
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        supabase.table("chunks").upsert(batch, on_conflict="id").execute()
        upserted += len(batch)
        logger.debug("Upserted batch %d-%d", i, i + len(batch))

    logger.info("Indexed %d chunks for client=%s", upserted, client_name)
    return upserted


def _deterministic_id(client_name: str, dedup_key: str) -> str:
    """Generate a deterministic UUID-shaped ID from client + dedup key.

    This ensures re-running ingestion overwrites existing rows instead of
    creating duplicates.
    """
    raw = f"{client_name}:{dedup_key}"
    h = hashlib.sha256(raw.encode()).hexdigest()
    # Format as UUID v4 shape for Supabase compatibility
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"
