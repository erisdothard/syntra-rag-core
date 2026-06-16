"""
Tests for core/query/retrieve.py — hybrid search + rerank.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.query.retrieve import _parse_ranking, _rerank, retrieve


def _make_candidate(content: str, score: float, domain_key: str = "K1") -> dict:
    """Helper to build a candidate dict."""
    return {
        "id": f"id-{domain_key}",
        "client": "test",
        "domain_key": domain_key,
        "kind": "Type",
        "variant": None,
        "content": content,
        "metadata": {},
        "score": score,
    }


class TestRetrieve:
    """retrieve() orchestrates embed -> hybrid search -> rerank -> validate."""

    @pytest.mark.asyncio
    async def test_returns_results(self, mock_supabase: MagicMock, mock_anthropic):
        candidates = [
            _make_candidate("Relevant doc", 0.9, "K1"),
            _make_candidate("Another doc", 0.8, "K2"),
        ]

        rpc_result = MagicMock()
        rpc_result.data = candidates
        mock_supabase.rpc.return_value.execute.return_value = rpc_result

        mock_anthropic.messages.create.return_value.content[0].text = "[0, 1]"

        with (
            patch("core.query.retrieve.embed_texts", new_callable=AsyncMock, return_value=[[0.1] * 1024]),
            patch("core.query.retrieve.get_supabase", return_value=mock_supabase),
            patch("core.query.retrieve.get_anthropic", return_value=mock_anthropic),
        ):
            results = await retrieve("test query", client_name="test")

        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_min_score_filters_low_scoring(self, mock_supabase: MagicMock, mock_anthropic):
        candidates = [
            _make_candidate("Low score", 0.2, "K1"),
            _make_candidate("Very low", 0.1, "K2"),
        ]

        rpc_result = MagicMock()
        rpc_result.data = candidates
        mock_supabase.rpc.return_value.execute.return_value = rpc_result

        with (
            patch("core.query.retrieve.embed_texts", new_callable=AsyncMock, return_value=[[0.1] * 1024]),
            patch("core.query.retrieve.get_supabase", return_value=mock_supabase),
            patch("core.query.retrieve.get_anthropic", return_value=mock_anthropic),
        ):
            results = await retrieve("test query", client_name="test", min_score=0.5)

        assert results == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_all_below_threshold(
        self, mock_supabase: MagicMock, mock_anthropic
    ):
        candidates = [_make_candidate("Marginal", 0.3, "K1")]

        rpc_result = MagicMock()
        rpc_result.data = candidates
        mock_supabase.rpc.return_value.execute.return_value = rpc_result

        with (
            patch("core.query.retrieve.embed_texts", new_callable=AsyncMock, return_value=[[0.1] * 1024]),
            patch("core.query.retrieve.get_supabase", return_value=mock_supabase),
            patch("core.query.retrieve.get_anthropic", return_value=mock_anthropic),
        ):
            results = await retrieve("test query", client_name="test", min_score=0.5)

        assert results == []


class TestParseRanking:
    """_parse_ranking extracts index arrays from LLM responses."""

    def test_valid_json(self):
        result = _parse_ranking("[2, 0, 1]", 3)
        assert result == [2, 0, 1]

    def test_malformed_json_returns_default(self):
        result = _parse_ranking("not json at all", 3)
        assert result == [0, 1, 2]

    def test_code_fences(self):
        raw = "```json\n[1, 0, 2]\n```"
        result = _parse_ranking(raw, 3)
        assert result == [1, 0, 2]

    def test_non_integer_list_returns_default(self):
        result = _parse_ranking('["a", "b"]', 3)
        assert result == [0, 1, 2]

    def test_empty_array(self):
        result = _parse_ranking("[]", 3)
        assert result == []


class TestRerank:
    """_rerank reorders candidates based on LLM ranking."""

    @pytest.mark.asyncio
    async def test_reorders_candidates(self, mock_anthropic):
        candidates = [
            _make_candidate("Doc A", 0.9, "K1"),
            _make_candidate("Doc B", 0.8, "K2"),
            _make_candidate("Doc C", 0.7, "K3"),
        ]

        # LLM says C is best, then A, then B
        mock_anthropic.messages.create.return_value.content[0].text = "[2, 0, 1]"

        with patch("core.query.retrieve.get_anthropic", return_value=mock_anthropic):
            result = await _rerank(
                query="test", candidates=candidates, top_k=2, model="test-model"
            )

        assert len(result) == 2
        assert result[0]["domain_key"] == "K3"  # Was index 2
        assert result[1]["domain_key"] == "K1"  # Was index 0
