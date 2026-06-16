"""
Tests for core/query/generate.py — Claude generation with evidence.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.query.generate import _format_evidence, generate
from core.trust.validate import GenerationResult


class TestGenerate:
    """generate() sends evidence + question to Claude and validates the result."""

    @pytest.mark.asyncio
    async def test_returns_generation_result(self, mock_anthropic):
        mock_anthropic.messages.create.return_value.content[0].text = (
            "This is the generated answer based on the evidence."
        )

        chunks = [
            {
                "domain_key": "K1",
                "kind": "Type",
                "variant": None,
                "content": "Evidence chunk content.",
                "metadata": {},
                "score": 0.9,
            }
        ]

        with patch("core.query.generate.get_anthropic", return_value=mock_anthropic):
            result = await generate(
                query="What is X?",
                chunks=chunks,
                system_prompt="You are a test assistant.",
            )

        assert isinstance(result, GenerationResult)
        assert result.answer == "This is the generated answer based on the evidence."
        assert result.query == "What is X?"
        assert len(result.chunks_used) == 1
        assert result.token_usage is not None
        assert result.token_usage.input_tokens == 100

    @pytest.mark.asyncio
    async def test_validates_output(self, mock_anthropic):
        # Empty answer should fail validation
        mock_anthropic.messages.create.return_value.content[0].text = "   "

        with patch("core.query.generate.get_anthropic", return_value=mock_anthropic):
            with pytest.raises(Exception):
                await generate(
                    query="What is X?",
                    chunks=[],
                    system_prompt="Test prompt.",
                )

    @pytest.mark.asyncio
    async def test_generate_with_empty_chunks(self, mock_anthropic):
        mock_anthropic.messages.create.return_value.content[0].text = (
            "I don't have enough evidence to answer."
        )

        with patch("core.query.generate.get_anthropic", return_value=mock_anthropic):
            result = await generate(
                query="Unanswerable?",
                chunks=[],
                system_prompt="Test prompt.",
            )

        assert isinstance(result, GenerationResult)
        assert len(result.chunks_used) == 0


class TestFormatEvidence:
    """_format_evidence assembles numbered evidence blocks."""

    def test_with_empty_chunks(self):
        result = _format_evidence([])
        assert result == "(No evidence retrieved.)"

    def test_with_multiple_chunks(self):
        chunks = [
            {
                "domain_key": "K1",
                "kind": "TypeA",
                "content": "First evidence.",
                "score": 0.95,
            },
            {
                "domain_key": "K2",
                "kind": "TypeB",
                "content": "Second evidence.",
                "score": 0.85,
            },
        ]
        result = _format_evidence(chunks)
        assert "[1] TypeA" in result
        assert "K1" in result
        assert "0.95" in result
        assert "[2] TypeB" in result
        assert "First evidence." in result
        assert "Second evidence." in result

    def test_missing_domain_key(self):
        chunks = [
            {
                "kind": "Type",
                "content": "No domain key chunk.",
                "score": 0.8,
            },
        ]
        result = _format_evidence(chunks)
        assert "[1] Type" in result
        assert "No domain key chunk." in result

    def test_missing_score_defaults_to_zero(self):
        chunks = [
            {
                "kind": "Type",
                "content": "No score.",
            },
        ]
        result = _format_evidence(chunks)
        assert "0.00" in result
