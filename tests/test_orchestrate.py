"""
Tests for core/query/orchestrate.py — the live pipeline router.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.query.orchestrate import OrchestratorResult, StageTiming, ask, _config_cache, _prompt_cache
from core.query.reshape import ReshapedQuery
from core.trust.evals.judge.rubrics import JudgeResult, JudgeScore
from core.trust.validate import GenerationResult, RetrievedChunk, TokenUsage


def _mock_generation() -> GenerationResult:
    """Build a mock GenerationResult."""
    return GenerationResult(
        query="rewritten question",
        answer="This is a grounded answer.",
        model="claude-sonnet-4-6",
        chunks_used=[
            RetrievedChunk(
                domain_key="K1",
                kind="Type",
                variant=None,
                content="Evidence chunk.",
                metadata={},
                score=0.9,
            )
        ],
        token_usage=TokenUsage(input_tokens=200, output_tokens=100),
    )


def _mock_judge_result(passed: bool = True) -> JudgeResult:
    """Build a mock JudgeResult."""
    return JudgeResult(
        faithfulness=JudgeScore(
            dimension="faithfulness", score=4, reasoning="Good.", passed=True
        ),
        relevance=JudgeScore(
            dimension="relevance", score=4, reasoning="Good.", passed=True
        ),
        passed=passed,
    )


def _mock_reshaped(original: str, sub_queries: list[str] | None = None) -> ReshapedQuery:
    """Build a mock ReshapedQuery."""
    return ReshapedQuery(
        original=original,
        rewritten=f"improved {original}",
        sub_queries=sub_queries or [],
    )


class TestAsk:
    """ask() routes through reshape -> retrieve -> generate -> judge."""

    @pytest.fixture(autouse=True)
    def clear_caches(self):
        """Clear config/prompt caches between tests."""
        _config_cache.clear()
        _prompt_cache.clear()
        yield
        _config_cache.clear()
        _prompt_cache.clear()

    @pytest.mark.asyncio
    async def test_direct_route(self, sample_config_path: Path):
        reshaped = _mock_reshaped("test question")
        generation = _mock_generation()
        judge_result = _mock_judge_result()

        with (
            patch("core.query.orchestrate.reshape", new_callable=AsyncMock, return_value=reshaped),
            patch("core.query.orchestrate.retrieve", new_callable=AsyncMock, return_value=[{"domain_key": "K1", "kind": "Type", "content": "evidence", "score": 0.9}]),
            patch("core.query.orchestrate.generate", new_callable=AsyncMock, return_value=generation),
            patch("core.query.orchestrate.judge", new_callable=AsyncMock, return_value=judge_result),
        ):
            result = await ask("test question", config_path=sample_config_path)

        assert isinstance(result, OrchestratorResult)
        assert result.route == "direct"
        assert result.generation.answer == "This is a grounded answer."
        assert result.judge_result is not None
        assert result.judge_result.passed

    @pytest.mark.asyncio
    async def test_no_evidence_route(self, sample_config_path: Path):
        reshaped = _mock_reshaped("test question")
        generation = _mock_generation()

        with (
            patch("core.query.orchestrate.reshape", new_callable=AsyncMock, return_value=reshaped),
            patch("core.query.orchestrate.retrieve", new_callable=AsyncMock, return_value=[]),
            patch("core.query.orchestrate.generate", new_callable=AsyncMock, return_value=generation),
            patch("core.query.orchestrate.judge", new_callable=AsyncMock) as mock_judge,
        ):
            result = await ask("test question", config_path=sample_config_path)

        assert result.route == "no_evidence"
        # Judge should NOT be called when there's no evidence
        mock_judge.assert_not_called()
        assert result.judge_result is None

    @pytest.mark.asyncio
    async def test_decomposed_route(self, sample_config_path: Path):
        reshaped = _mock_reshaped("complex question", sub_queries=["sub1", "sub2"])
        generation = _mock_generation()
        judge_result = _mock_judge_result()

        with (
            patch("core.query.orchestrate.reshape", new_callable=AsyncMock, return_value=reshaped),
            patch("core.query.orchestrate.retrieve", new_callable=AsyncMock, return_value=[{"domain_key": "K1", "kind": "Type", "content": "evidence", "score": 0.9}]),
            patch("core.query.orchestrate.generate", new_callable=AsyncMock, return_value=generation),
            patch("core.query.orchestrate.judge", new_callable=AsyncMock, return_value=judge_result),
        ):
            result = await ask("complex question", config_path=sample_config_path)

        assert result.route == "decomposed"

    @pytest.mark.asyncio
    async def test_config_caching_works(self, sample_config_path: Path):
        reshaped = _mock_reshaped("q")
        generation = _mock_generation()

        with (
            patch("core.query.orchestrate.reshape", new_callable=AsyncMock, return_value=reshaped),
            patch("core.query.orchestrate.retrieve", new_callable=AsyncMock, return_value=[]),
            patch("core.query.orchestrate.generate", new_callable=AsyncMock, return_value=generation),
        ):
            await ask("q1", config_path=sample_config_path)
            await ask("q2", config_path=sample_config_path)

        # Config should be cached after first read
        key = str(sample_config_path)
        assert key in _config_cache


class TestStageTiming:
    """StageTiming dataclass captures per-stage wall-clock timing."""

    def test_defaults_to_zero(self):
        timing = StageTiming()
        assert timing.reshape_ms == 0.0
        assert timing.retrieve_ms == 0.0
        assert timing.generate_ms == 0.0
        assert timing.judge_ms == 0.0

    def test_populated(self):
        timing = StageTiming(
            reshape_ms=10.5,
            retrieve_ms=150.3,
            generate_ms=500.0,
            judge_ms=80.2,
        )
        assert timing.reshape_ms == 10.5
        assert timing.generate_ms == 500.0
