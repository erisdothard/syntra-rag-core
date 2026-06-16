"""
Tests for core/trust/evals/judge/rubrics.py — LLM-as-judge scoring.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.trust.evals.judge.rubrics import (
    JudgeResult,
    JudgeScore,
    _parse_judge_response,
    judge,
)


class TestJudge:
    """judge() runs faithfulness + relevance scoring in parallel."""

    @pytest.mark.asyncio
    async def test_returns_judge_result(self, mock_anthropic):
        mock_anthropic.messages.create.return_value.content[0].text = (
            '{"score": 4, "reasoning": "Well grounded."}'
        )

        with patch(
            "core.trust.evals.judge.rubrics.get_anthropic",
            return_value=mock_anthropic,
        ):
            result = await judge(
                question="What is X?",
                answer="X is defined as Y.",
                evidence_chunks=["Evidence about X being Y."],
                model="test-model",
            )

        assert isinstance(result, JudgeResult)
        assert result.faithfulness.score == 4
        assert result.relevance.score == 4
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_runs_both_rubrics_in_parallel(self, mock_anthropic):
        call_count = 0

        async def counting_create(**kwargs):
            nonlocal call_count
            call_count += 1
            response = MagicMock()
            response.content = [MagicMock()]
            response.content[0].text = '{"score": 5, "reasoning": "Perfect."}'
            return response

        mock_anthropic.messages.create = AsyncMock(side_effect=counting_create)

        with patch(
            "core.trust.evals.judge.rubrics.get_anthropic",
            return_value=mock_anthropic,
        ):
            result = await judge(
                question="Q",
                answer="A",
                evidence_chunks=["E"],
                model="test-model",
            )

        # Both faithfulness and relevance called
        assert call_count == 2
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_failing_scores_flag_result(self, mock_anthropic):
        mock_anthropic.messages.create.return_value.content[0].text = (
            '{"score": 2, "reasoning": "Poor."}'
        )

        with patch(
            "core.trust.evals.judge.rubrics.get_anthropic",
            return_value=mock_anthropic,
        ):
            result = await judge(
                question="Q",
                answer="A",
                evidence_chunks=["E"],
                model="test-model",
                faithfulness_threshold=3,
                relevance_threshold=3,
            )

        assert result.faithfulness.passed is False
        assert result.relevance.passed is False
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_api_failure_returns_score_1(self, mock_anthropic):
        mock_anthropic.messages.create = AsyncMock(
            side_effect=Exception("API error")
        )

        with patch(
            "core.trust.evals.judge.rubrics.get_anthropic",
            return_value=mock_anthropic,
        ):
            result = await judge(
                question="Q",
                answer="A",
                evidence_chunks=["E"],
                model="test-model",
            )

        assert result.faithfulness.score == 1
        assert result.relevance.score == 1


class TestParseJudgeResponse:
    """_parse_judge_response handles various response formats."""

    def test_valid_json(self):
        result = _parse_judge_response('{"score": 4, "reasoning": "Good answer."}')
        assert result["score"] == 4
        assert result["reasoning"] == "Good answer."

    def test_code_fences(self):
        raw = '```json\n{"score": 5, "reasoning": "Perfect."}\n```'
        result = _parse_judge_response(raw)
        assert result["score"] == 5

    def test_invalid_json_returns_score_1(self):
        result = _parse_judge_response("not valid json")
        assert result["score"] == 1
        assert "Unparseable" in result["reasoning"]

    def test_clamps_score_above_5(self):
        result = _parse_judge_response('{"score": 10, "reasoning": "Inflated."}')
        assert result["score"] == 1  # Out of range -> clamped to 1

    def test_clamps_score_below_1(self):
        result = _parse_judge_response('{"score": 0, "reasoning": "Too low."}')
        assert result["score"] == 1  # Out of range -> clamped to 1

    def test_non_integer_score_returns_1(self):
        result = _parse_judge_response('{"score": "four", "reasoning": "Not int."}')
        assert result["score"] == 1

    def test_missing_score_defaults_to_1(self):
        result = _parse_judge_response('{"reasoning": "No score field."}')
        assert result["score"] == 1

    def test_missing_reasoning_defaults(self):
        result = _parse_judge_response('{"score": 3}')
        assert result["reasoning"] == "No reasoning provided"
