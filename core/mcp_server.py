"""
core/mcp_server.py

MCP server exposing the RAG pipeline as tools. Industry-neutral.

Tools:
  - ask(question)          — full pipeline: reshape → retrieve → generate → judge
  - get_chunk(domain_key)  — direct chunk lookup by domain_key
  - get_traces(limit)      — recent pipeline traces for observability
  - get_flagged(limit)     — traces where the judge flagged the answer

The server is configured at startup with a client config path. All domain
behavior comes from that config — the server code has no domain terms.

Build order: Step 10 — last.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from core.db import get_supabase
from core.observability.trace import get_flagged_traces, get_recent_traces, get_trace, trace_result
from core.query.orchestrate import ask

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "syntra-rag-core",
    description="Industry-neutral RAG pipeline. One core, many clients.",
)

# Client config path — set via environment variable
_CONFIG_PATH: str = os.environ.get("RAG_CLIENT_CONFIG", "")


_cached_client_name: str | None = None


def _get_client_name() -> str:
    """Read the client name from config for tracing (cached after first read)."""
    global _cached_client_name
    if _cached_client_name is None:
        import yaml

        config_path = Path(_CONFIG_PATH)
        yaml_path = (
            config_path
            if config_path.suffix in (".yaml", ".yml")
            else config_path / "config.yaml"
        )
        with open(yaml_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        _cached_client_name = config.get("client", {}).get("name", "unknown")
    return _cached_client_name


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def ask_question(question: str) -> dict:
    """Ask a question and get a grounded answer from the RAG pipeline.

    The pipeline reshapes your question for better retrieval, searches the
    indexed knowledge base, generates an answer with Claude, and optionally
    scores the answer for faithfulness and relevance.

    Args:
        question: Your question in natural language.

    Returns:
        Dict with answer, route taken, judge scores, and trace ID.
    """
    start = time.time()

    result = await ask(question, config_path=_CONFIG_PATH)

    client_name = _get_client_name()
    trace = trace_result(
        result=result,
        client_name=client_name,
        start_time=start,
    )

    response = {
        "answer": result.generation.answer,
        "route": result.route,
        "trace_id": trace.trace_id,
        "chunks_used": len(result.generation.chunks_used),
        "reshaped_query": result.reshaped_query.rewritten,
    }

    if result.judge_result is not None:
        response["judge"] = {
            "faithfulness": result.judge_result.faithfulness.score,
            "relevance": result.judge_result.relevance.score,
            "passed": result.judge_result.passed,
        }

    if result.generation.token_usage is not None:
        response["token_usage"] = {
            "input": result.generation.token_usage.input_tokens,
            "output": result.generation.token_usage.output_tokens,
        }

    response["duration_ms"] = round((time.time() - start) * 1000)

    return response


@mcp.tool()
async def get_chunk(domain_key: str, client_name: str | None = None) -> dict:
    """Look up a specific chunk by its domain key.

    Args:
        domain_key: The domain-specific key to look up (e.g. a code, ID, etc.)
        client_name: Optional client filter. Defaults to the configured client.

    Returns:
        The matching chunk(s) or an empty result.
    """
    supabase = get_supabase()

    name = client_name or _get_client_name()

    result = (
        supabase.table("chunks")
        .select("id, client, domain_key, kind, variant, content, metadata")
        .eq("client", name)
        .eq("domain_key", domain_key)
        .execute()
    )

    return {
        "domain_key": domain_key,
        "client": name,
        "count": len(result.data),
        "chunks": result.data,
    }


@mcp.tool()
async def get_traces(limit: int = 20) -> dict:
    """Get recent pipeline execution traces.

    Args:
        limit: Number of traces to return (max 100).

    Returns:
        List of recent trace summaries.
    """
    clamped = min(max(limit, 1), 100)
    traces = get_recent_traces(clamped)
    return {
        "count": len(traces),
        "traces": traces,
    }


@mcp.tool()
async def get_flagged(limit: int = 20) -> dict:
    """Get recent traces where the judge flagged the answer.

    These are answers that scored below the faithfulness or relevance
    threshold and may need human review.

    Args:
        limit: Number of flagged traces to return (max 100).

    Returns:
        List of flagged trace summaries.
    """
    clamped = min(max(limit, 1), 100)
    traces = get_flagged_traces(clamped)
    return {
        "count": len(traces),
        "flagged_traces": traces,
    }


@mcp.tool()
async def get_trace_detail(trace_id: str) -> dict:
    """Get full details for a specific trace by ID.

    Args:
        trace_id: The trace ID from a previous ask_question response.

    Returns:
        Full trace including all pipeline events, or error if not found.
    """
    trace = get_trace(trace_id)
    if trace is None:
        return {"error": f"Trace {trace_id} not found (buffer holds last 200 traces)"}
    return trace


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    logger.info("Starting MCP server with config: %s", _CONFIG_PATH)
    mcp.run()
