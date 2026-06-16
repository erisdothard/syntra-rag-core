"""
Tests for core/ingestion/index.py — embed + upsert to Supabase pgvector.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.ingestion.index import _deterministic_id, embed_texts, index_chunks
from core.interfaces import Chunk


class TestEmbedTexts:
    """embed_texts calls Voyage AI and returns vectors."""

    @pytest.mark.asyncio
    async def test_returns_correct_shape(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"embedding": [0.1] * 1024},
                {"embedding": [0.2] * 1024},
            ]
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("core.ingestion.index.httpx.AsyncClient", return_value=mock_client):
            result = await embed_texts(
                ["text one", "text two"],
                api_key="test-key",
            )

        assert len(result) == 2
        assert len(result[0]) == 1024
        assert len(result[1]) == 1024

    @pytest.mark.asyncio
    async def test_handles_429_retry(self):
        rate_limited_response = MagicMock()
        rate_limited_response.status_code = 429

        ok_response = MagicMock()
        ok_response.status_code = 200
        ok_response.raise_for_status = MagicMock()
        ok_response.json.return_value = {
            "data": [{"embedding": [0.1] * 1024}]
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            side_effect=[rate_limited_response, ok_response]
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("core.ingestion.index.httpx.AsyncClient", return_value=mock_client),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await embed_texts(["retry text"], api_key="test-key")

        assert len(result) == 1
        assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_raises_without_api_key(self):
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(RuntimeError, match="VOYAGE_API_KEY"):
                await embed_texts(["text"], api_key=None)


class TestIndexChunks:
    """index_chunks validates, embeds, and upserts."""

    @pytest.mark.asyncio
    async def test_calls_upsert_with_correct_data(self, mock_supabase: MagicMock):
        chunks = [
            Chunk(domain_key="K1", kind="Type", variant="v1", content="Content one."),
            Chunk(domain_key="K2", kind="Type", variant="v2", content="Content two."),
        ]
        dedup_keys = ["K1|v1", "K2|v2"]

        mock_embeddings = [[0.1] * 1024, [0.2] * 1024]

        with (
            patch("core.ingestion.index.embed_texts", new_callable=AsyncMock, return_value=mock_embeddings),
            patch("core.ingestion.index.get_supabase", return_value=mock_supabase),
        ):
            count = await index_chunks(
                chunks, client_name="test_client", dedup_keys=dedup_keys
            )

        assert count == 2
        mock_supabase.table.assert_called_with("chunks")
        mock_supabase.table.return_value.upsert.assert_called_once()

        # Verify the row structure
        call_args = mock_supabase.table.return_value.upsert.call_args
        rows = call_args[0][0]
        assert len(rows) == 2
        assert rows[0]["client"] == "test_client"
        assert rows[0]["domain_key"] == "K1"

    @pytest.mark.asyncio
    async def test_validates_before_embedding(self):
        chunks = [
            Chunk(domain_key="K", kind="   ", variant=None, content="Content."),
        ]
        dedup_keys = ["K|none"]

        with pytest.raises(Exception):
            await index_chunks(chunks, client_name="test", dedup_keys=dedup_keys)

    @pytest.mark.asyncio
    async def test_empty_chunks_returns_zero(self):
        count = await index_chunks([], client_name="test", dedup_keys=[])
        assert count == 0

    @pytest.mark.asyncio
    async def test_mismatched_lengths_raises(self):
        chunks = [Chunk(domain_key="K", kind="Type", content="Content.")]
        with pytest.raises(ValueError, match="same length"):
            await index_chunks(chunks, client_name="test", dedup_keys=["a", "b"])


class TestDeterministicId:
    """_deterministic_id produces stable, UUID-shaped IDs."""

    def test_is_stable(self):
        id1 = _deterministic_id("client_a", "key_1")
        id2 = _deterministic_id("client_a", "key_1")
        assert id1 == id2

    def test_different_inputs_produce_different_ids(self):
        id1 = _deterministic_id("client_a", "key_1")
        id2 = _deterministic_id("client_a", "key_2")
        assert id1 != id2

    def test_uuid_shape(self):
        result = _deterministic_id("client", "key")
        parts = result.split("-")
        assert len(parts) == 5
        assert len(parts[0]) == 8
        assert len(parts[1]) == 4
        assert len(parts[2]) == 4
        assert len(parts[3]) == 4
        assert len(parts[4]) == 12
