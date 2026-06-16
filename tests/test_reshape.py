"""
Tests for core/query/reshape.py — query rewriting.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.query.reshape import ReshapedQuery, _parse_response, reshape


class TestReshape:
    """reshape() rewrites queries using vocabulary hints."""

    @pytest.mark.asyncio
    async def test_returns_reshaped_query(self, mock_anthropic):
        mock_anthropic.messages.create.return_value.content[0].text = (
            '{"rewritten": "improved question about term_a", "sub_queries": []}'
        )

        with patch("core.query.reshape.get_anthropic", return_value=mock_anthropic):
            result = await reshape(
                "original question",
                vocabulary_hints=["term_a", "term_b"],
            )

        assert isinstance(result, ReshapedQuery)
        assert result.original == "original question"
        assert "improved" in result.rewritten
        assert result.sub_queries == []

    @pytest.mark.asyncio
    async def test_empty_question_returns_original(self):
        result = await reshape("", vocabulary_hints=["hint"])
        assert result.original == ""
        assert result.rewritten == ""
        assert result.sub_queries == []

    @pytest.mark.asyncio
    async def test_whitespace_only_returns_original(self):
        result = await reshape("   ", vocabulary_hints=["hint"])
        assert result.original == "   "
        assert result.rewritten == "   "

    @pytest.mark.asyncio
    async def test_falls_back_on_api_failure(self, mock_anthropic):
        mock_anthropic.messages.create = AsyncMock(
            side_effect=Exception("API down")
        )

        with patch("core.query.reshape.get_anthropic", return_value=mock_anthropic):
            result = await reshape("my question", vocabulary_hints=["hint"])

        assert result.rewritten == "my question"
        assert result.sub_queries == []

    @pytest.mark.asyncio
    async def test_with_sub_queries(self, mock_anthropic):
        mock_anthropic.messages.create.return_value.content[0].text = (
            '{"rewritten": "complex query", "sub_queries": ["sub q1", "sub q2"]}'
        )

        with patch("core.query.reshape.get_anthropic", return_value=mock_anthropic):
            result = await reshape(
                "complex multi-part question",
                vocabulary_hints=["term"],
            )

        assert len(result.sub_queries) == 2
        assert result.sub_queries[0] == "sub q1"


class TestParseResponse:
    """_parse_response handles various LLM response formats."""

    def test_valid_json(self):
        raw = '{"rewritten": "better query", "sub_queries": ["a", "b"]}'
        result = _parse_response(raw)
        assert result["rewritten"] == "better query"
        assert result["sub_queries"] == ["a", "b"]

    def test_code_fences(self):
        raw = '```json\n{"rewritten": "fenced query", "sub_queries": []}\n```'
        result = _parse_response(raw)
        assert result["rewritten"] == "fenced query"

    def test_invalid_json_returns_empty_dict(self):
        result = _parse_response("this is not json")
        assert result == {}

    def test_non_dict_json_returns_empty_dict(self):
        result = _parse_response("[1, 2, 3]")
        assert result == {}

    def test_non_list_sub_queries_replaced_with_empty(self):
        raw = '{"rewritten": "q", "sub_queries": "not a list"}'
        result = _parse_response(raw)
        assert result["sub_queries"] == []

    def test_filters_non_string_sub_queries(self):
        raw = '{"rewritten": "q", "sub_queries": ["valid", 123, null, "also valid"]}'
        result = _parse_response(raw)
        assert result["sub_queries"] == ["valid", "also valid"]

    def test_filters_empty_string_sub_queries(self):
        raw = '{"rewritten": "q", "sub_queries": ["valid", "  ", ""]}'
        result = _parse_response(raw)
        assert result["sub_queries"] == ["valid"]
