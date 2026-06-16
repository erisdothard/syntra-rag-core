"""
Tests for core/observability/trace.py — structured tracing.
"""

from __future__ import annotations

import time

import pytest

from core.observability.trace import (
    Trace,
    TraceEvent,
    _TRACE_BUFFER,
    _serialize,
    get_flagged_traces,
    get_recent_traces,
    get_trace,
    trace_result,
)
from core.query.orchestrate import OrchestratorResult, StageTiming
from core.query.reshape import ReshapedQuery
from core.trust.evals.judge.rubrics import JudgeResult, JudgeScore
from core.trust.validate import GenerationResult, RetrievedChunk, TokenUsage


def _build_orchestrator_result(
    route: str = "direct",
    judge_passed: bool = True,
    with_judge: bool = True,
) -> OrchestratorResult:
    """Build a test OrchestratorResult."""
    generation = GenerationResult(
        query="reshaped question",
        answer="Test answer.",
        model="claude-sonnet-4-6",
        chunks_used=[
            RetrievedChunk(
                domain_key="K1",
                kind="Type",
                variant=None,
                content="Evidence.",
                metadata={},
                score=0.9,
            )
        ],
        token_usage=TokenUsage(input_tokens=100, output_tokens=50),
    )

    reshaped = ReshapedQuery(
        original="original question",
        rewritten="reshaped question",
        sub_queries=[],
    )

    judge_result = None
    if with_judge:
        judge_result = JudgeResult(
            faithfulness=JudgeScore(
                dimension="faithfulness",
                score=4 if judge_passed else 2,
                reasoning="Test.",
                passed=judge_passed,
            ),
            relevance=JudgeScore(
                dimension="relevance",
                score=4 if judge_passed else 2,
                reasoning="Test.",
                passed=judge_passed,
            ),
            passed=judge_passed,
        )

    return OrchestratorResult(
        route=route,
        generation=generation,
        judge_result=judge_result,
        reshaped_query=reshaped,
        timing=StageTiming(
            reshape_ms=10.0,
            retrieve_ms=150.0,
            generate_ms=500.0,
            judge_ms=80.0,
        ),
    )


@pytest.fixture(autouse=True)
def clear_buffer():
    """Clear the trace buffer before and after each test."""
    _TRACE_BUFFER.clear()
    yield
    _TRACE_BUFFER.clear()


class TestTraceResult:
    """trace_result builds correct structure from OrchestratorResult."""

    def test_builds_correct_structure(self):
        result = _build_orchestrator_result()
        start = time.time()
        trace = trace_result(result=result, client_name="test_client", start_time=start)

        assert isinstance(trace, Trace)
        assert trace.client == "test_client"
        assert trace.route == "direct"
        assert trace.question == "original question"
        assert len(trace.trace_id) == 12
        assert trace.flagged is False

    def test_flagged_when_judge_fails(self):
        result = _build_orchestrator_result(judge_passed=False)
        trace = trace_result(result=result, client_name="test", start_time=time.time())

        assert trace.flagged is True
        assert trace.flag_reason is not None
        assert "faithfulness" in trace.flag_reason

    def test_events_populated(self):
        result = _build_orchestrator_result()
        trace = trace_result(result=result, client_name="test", start_time=time.time())

        stages = [e.stage for e in trace.events]
        assert "reshape" in stages
        assert "retrieve" in stages
        assert "generate" in stages
        assert "judge" in stages

    def test_no_judge_event_when_no_judge(self):
        result = _build_orchestrator_result(with_judge=False)
        trace = trace_result(result=result, client_name="test", start_time=time.time())

        stages = [e.stage for e in trace.events]
        assert "judge" not in stages
        assert trace.flagged is False


class TestRingBuffer:
    """Ring buffer respects maxlen and stores traces."""

    def test_respects_maxlen(self):
        assert _TRACE_BUFFER.maxlen == 200

        # Add more than maxlen
        for i in range(210):
            _TRACE_BUFFER.append({"trace_id": f"trace_{i}", "flagged": False})

        assert len(_TRACE_BUFFER) == 200
        # Oldest should be evicted
        assert _TRACE_BUFFER[0]["trace_id"] == "trace_10"

    def test_stores_traces_from_trace_result(self):
        result = _build_orchestrator_result()
        trace_result(result=result, client_name="test", start_time=time.time())

        assert len(_TRACE_BUFFER) == 1


class TestGetRecentTraces:
    """get_recent_traces returns newest first."""

    def test_returns_newest_first(self):
        for i in range(5):
            _TRACE_BUFFER.append({"trace_id": f"trace_{i}", "flagged": False})

        recent = get_recent_traces(limit=3)
        assert len(recent) == 3
        assert recent[0]["trace_id"] == "trace_4"
        assert recent[1]["trace_id"] == "trace_3"
        assert recent[2]["trace_id"] == "trace_2"

    def test_returns_all_when_limit_exceeds_buffer(self):
        _TRACE_BUFFER.append({"trace_id": "only_one", "flagged": False})
        recent = get_recent_traces(limit=100)
        assert len(recent) == 1


class TestGetFlaggedTraces:
    """get_flagged_traces filters to flagged-only."""

    def test_filters_correctly(self):
        _TRACE_BUFFER.append({"trace_id": "good", "flagged": False})
        _TRACE_BUFFER.append({"trace_id": "bad", "flagged": True})
        _TRACE_BUFFER.append({"trace_id": "also_good", "flagged": False})
        _TRACE_BUFFER.append({"trace_id": "also_bad", "flagged": True})

        flagged = get_flagged_traces()
        assert len(flagged) == 2
        assert all(t["flagged"] for t in flagged)

    def test_returns_empty_when_none_flagged(self):
        _TRACE_BUFFER.append({"trace_id": "ok", "flagged": False})
        flagged = get_flagged_traces()
        assert flagged == []


class TestGetTrace:
    """get_trace finds by ID."""

    def test_finds_existing_trace(self):
        _TRACE_BUFFER.append({"trace_id": "abc123", "flagged": False, "route": "direct"})
        found = get_trace("abc123")
        assert found is not None
        assert found["trace_id"] == "abc123"

    def test_returns_none_for_missing_id(self):
        _TRACE_BUFFER.append({"trace_id": "abc123", "flagged": False})
        assert get_trace("nonexistent") is None
