"""
Tests for core/trust/validate.py — Pydantic validation layer.
"""

from __future__ import annotations

import pytest

from core.trust.validate import (
    ChunkRecord,
    GenerationResult,
    RetrievalResult,
    ValidationError,
    validate_chunk,
    validate_generation,
    validate_retrieval,
)


class TestValidateChunk:
    """validate_chunk enforces non-empty content and kind."""

    def test_passes_with_valid_data(self):
        result = validate_chunk(
            domain_key="KEY-1",
            kind="Document",
            variant="summary",
            content="Valid content here.",
            metadata={"src": "test"},
            dedup_key="KEY-1|summary",
        )
        assert isinstance(result, ChunkRecord)
        assert result.domain_key == "KEY-1"

    def test_rejects_empty_content(self):
        with pytest.raises(ValidationError, match="chunk"):
            validate_chunk(
                domain_key="KEY-1",
                kind="Document",
                variant=None,
                content="   ",
                metadata={},
                dedup_key="KEY-1|none",
            )

    def test_rejects_empty_kind(self):
        with pytest.raises(ValidationError, match="chunk"):
            validate_chunk(
                domain_key="KEY-1",
                kind="   ",
                variant=None,
                content="Valid content.",
                metadata={},
                dedup_key="KEY-1|none",
            )

    def test_allows_none_domain_key(self):
        result = validate_chunk(
            domain_key=None,
            kind="Record",
            variant=None,
            content="Content.",
            metadata={},
            dedup_key="none|none",
        )
        assert result.domain_key is None

    def test_strips_whitespace_from_content(self):
        result = validate_chunk(
            domain_key="K",
            kind="Type",
            variant=None,
            content="  trimmed  ",
            metadata={},
            dedup_key="K|none",
        )
        assert result.content == "trimmed"


class TestValidateRetrieval:
    """validate_retrieval enforces non-empty query and valid chunk scores."""

    def test_passes_with_valid_data(self):
        result = validate_retrieval(
            query="What is the answer?",
            chunks=[
                {
                    "domain_key": "K1",
                    "kind": "Type",
                    "variant": None,
                    "content": "Chunk content.",
                    "metadata": {},
                    "score": 0.85,
                }
            ],
            total_candidates=5,
        )
        assert isinstance(result, RetrievalResult)
        assert len(result.chunks) == 1

    def test_rejects_empty_query(self):
        with pytest.raises(ValidationError, match="retrieval"):
            validate_retrieval(
                query="   ",
                chunks=[],
                total_candidates=0,
            )

    def test_passes_with_empty_chunks_list(self):
        result = validate_retrieval(
            query="Valid query",
            chunks=[],
            total_candidates=0,
        )
        assert len(result.chunks) == 0


class TestValidateGeneration:
    """validate_generation enforces non-empty answer."""

    def test_passes_with_valid_data(self):
        result = validate_generation(
            query="What is X?",
            answer="X is the answer.",
            model="claude-sonnet-4-6",
            chunks_used=[
                {
                    "domain_key": "K1",
                    "kind": "Type",
                    "variant": None,
                    "content": "Evidence.",
                    "metadata": {},
                    "score": 0.9,
                }
            ],
            token_usage={"input_tokens": 100, "output_tokens": 50},
        )
        assert isinstance(result, GenerationResult)
        assert result.answer == "X is the answer."

    def test_rejects_empty_answer(self):
        with pytest.raises(ValidationError, match="generation"):
            validate_generation(
                query="What is X?",
                answer="   ",
                model="claude-sonnet-4-6",
                chunks_used=[],
            )

    def test_passes_without_token_usage(self):
        result = validate_generation(
            query="Question?",
            answer="Answer.",
            model="test-model",
            chunks_used=[],
            token_usage=None,
        )
        assert result.token_usage is None

    def test_strips_whitespace_from_answer(self):
        result = validate_generation(
            query="Q?",
            answer="  Answer with whitespace  ",
            model="test-model",
            chunks_used=[],
        )
        assert result.answer == "Answer with whitespace"
