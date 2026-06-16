"""
core/observability/trace.py — LIVE

Structured tracing for every live request. Captures the full pipeline
execution: what was asked, how it was reshaped, what was retrieved,
what was kept after rerank, what was generated, and whether the judge
flagged it.

Two output modes:
  1. Structured log lines (JSON) — for log aggregation (stdout, file, etc.)
  2. In-memory trace store — for MCP server introspection and debugging

Industry-neutral. Traces capture pipeline mechanics, not domain content.

Build order: Step 9.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from core.query.orchestrate import OrchestratorResult

logger = logging.getLogger(__name__)

# In-memory ring buffer for recent traces (MCP introspection)
_TRACE_BUFFER: list[dict[str, Any]] = []
_BUFFER_MAX = 200


@dataclass
class TraceEvent:
    """A single pipeline event within a trace."""

    stage: str  # "reshape", "retrieve", "generate", "judge"
    timestamp: float
    duration_ms: float
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Trace:
    """Full trace for one live request."""

    trace_id: str
    client: str
    timestamp: float
    question: str
    route: str
    events: list[TraceEvent] = field(default_factory=list)
    flagged: bool = False
    flag_reason: str | None = None
    total_duration_ms: float = 0.0


def trace_result(
    *,
    result: OrchestratorResult,
    client_name: str,
    start_time: float,
) -> Trace:
    """Build a Trace from an OrchestratorResult and emit it.

    Call this after orchestrate.ask() returns. It captures the full
    pipeline execution for logging and introspection.

    Args:
        result:       The OrchestratorResult from orchestrate.ask().
        client_name:  Client identifier.
        start_time:   time.time() captured before the ask() call.

    Returns:
        The completed Trace object.
    """
    now = time.time()
    trace_id = uuid.uuid4().hex[:12]

    events: list[TraceEvent] = []

    # Reshape event
    reshaped = result.reshaped_query
    events.append(TraceEvent(
        stage="reshape",
        timestamp=start_time,
        duration_ms=0.0,  # reshape timing not captured individually — see note below
        data={
            "original": reshaped.original,
            "rewritten": reshaped.rewritten,
            "sub_queries": reshaped.sub_queries,
            "decomposed": len(reshaped.sub_queries) > 0,
        },
    ))

    # Retrieve event
    gen = result.generation
    chunks_used = gen.chunks_used
    events.append(TraceEvent(
        stage="retrieve",
        timestamp=start_time,
        duration_ms=0.0,
        data={
            "chunks_returned": len(chunks_used),
            "chunk_kinds": list({c.kind for c in chunks_used}),
            "top_score": max((c.score for c in chunks_used), default=0.0),
            "min_score": min((c.score for c in chunks_used), default=0.0),
        },
    ))

    # Generate event
    token_usage = {}
    if gen.token_usage:
        token_usage = {
            "input_tokens": gen.token_usage.input_tokens,
            "output_tokens": gen.token_usage.output_tokens,
        }

    events.append(TraceEvent(
        stage="generate",
        timestamp=start_time,
        duration_ms=0.0,
        data={
            "model": gen.model,
            "answer_length": len(gen.answer),
            "token_usage": token_usage,
        },
    ))

    # Judge event
    flagged = False
    flag_reason = None

    if result.judge_result is not None:
        jr = result.judge_result
        flagged = not jr.passed
        if flagged:
            reasons = []
            if not jr.faithfulness.passed:
                reasons.append(f"faithfulness={jr.faithfulness.score}")
            if not jr.relevance.passed:
                reasons.append(f"relevance={jr.relevance.score}")
            flag_reason = ", ".join(reasons)

        events.append(TraceEvent(
            stage="judge",
            timestamp=start_time,
            duration_ms=0.0,
            data={
                "faithfulness_score": jr.faithfulness.score,
                "faithfulness_reasoning": jr.faithfulness.reasoning,
                "relevance_score": jr.relevance.score,
                "relevance_reasoning": jr.relevance.reasoning,
                "passed": jr.passed,
            },
        ))

    trace = Trace(
        trace_id=trace_id,
        client=client_name,
        timestamp=start_time,
        question=reshaped.original,
        route=result.route,
        events=events,
        flagged=flagged,
        flag_reason=flag_reason,
        total_duration_ms=(now - start_time) * 1000,
    )

    _emit(trace)
    return trace


# ---------------------------------------------------------------------------
# Emit — structured logging + buffer
# ---------------------------------------------------------------------------


def _emit(trace: Trace) -> None:
    """Log the trace as structured JSON and store in the ring buffer."""
    record = _serialize(trace)

    # Structured log line
    logger.info(
        "TRACE %s client=%s route=%s flagged=%s duration=%.0fms",
        trace.trace_id,
        trace.client,
        trace.route,
        trace.flagged,
        trace.total_duration_ms,
    )
    logger.debug("TRACE_DETAIL %s", json.dumps(record))

    # Ring buffer for introspection
    _TRACE_BUFFER.append(record)
    if len(_TRACE_BUFFER) > _BUFFER_MAX:
        _TRACE_BUFFER.pop(0)


def _serialize(trace: Trace) -> dict[str, Any]:
    """Convert a Trace to a JSON-serializable dict."""
    return {
        "trace_id": trace.trace_id,
        "client": trace.client,
        "timestamp": trace.timestamp,
        "question": trace.question,
        "route": trace.route,
        "flagged": trace.flagged,
        "flag_reason": trace.flag_reason,
        "total_duration_ms": trace.total_duration_ms,
        "events": [
            {
                "stage": e.stage,
                "timestamp": e.timestamp,
                "duration_ms": e.duration_ms,
                "data": e.data,
            }
            for e in trace.events
        ],
    }


# ---------------------------------------------------------------------------
# Buffer access — for MCP server and debugging
# ---------------------------------------------------------------------------


def get_recent_traces(limit: int = 20) -> list[dict[str, Any]]:
    """Return the most recent traces from the ring buffer."""
    return list(reversed(_TRACE_BUFFER[-limit:]))


def get_trace(trace_id: str) -> dict[str, Any] | None:
    """Retrieve a single trace by ID from the buffer."""
    for t in _TRACE_BUFFER:
        if t["trace_id"] == trace_id:
            return t
    return None


def get_flagged_traces(limit: int = 20) -> list[dict[str, Any]]:
    """Return recent traces where the judge flagged the answer."""
    flagged = [t for t in _TRACE_BUFFER if t.get("flagged")]
    return list(reversed(flagged[-limit:]))
