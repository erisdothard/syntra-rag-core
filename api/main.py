"""
api/main.py — FastAPI server wrapping the RAG pipeline.

Endpoints:
  POST /ask          — stream an answer via SSE
  GET  /traces       — recent pipeline traces
  GET  /traces/{id}  — single trace detail
  GET  /health       — health check
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

load_dotenv()

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.observability.trace import get_flagged_traces, get_recent_traces, get_trace, trace_result
from core.query.generate import generate_stream
from core.query.orchestrate import ask, StageTiming

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

_CONFIG_PATH = os.environ.get("RAG_CLIENT_CONFIG", "clients/fhir_mapping/config.yaml")

app = FastAPI(
    title="syntra-rag-core",
    description="Industry-neutral RAG pipeline API",
    version="0.1.0",
)

# CORS — allow the Vercel frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AskRequest(BaseModel):
    question: str
    stream: bool = True


@app.post("/ask")
async def ask_endpoint(req: AskRequest):
    """Full pipeline: reshape -> retrieve -> generate -> judge.

    If stream=True (default), returns SSE with token-by-token answer
    followed by metadata. If stream=False, returns JSON.
    """
    start = time.time()

    if req.stream:
        return StreamingResponse(
            _stream_answer(req.question, start),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # Non-streaming: run full pipeline
    result = await ask(req.question, config_path=_CONFIG_PATH)

    client_name = _get_client_name()
    trace = trace_result(result=result, client_name=client_name, start_time=start)

    response = {
        "answer": result.generation.answer,
        "route": result.route,
        "trace_id": trace.trace_id,
        "chunks_used": [
            {
                "domain_key": c.domain_key,
                "kind": c.kind,
                "content": c.content,
                "score": c.score,
            }
            for c in result.generation.chunks_used
        ],
        "timing": {
            "reshape_ms": round(result.timing.reshape_ms),
            "retrieve_ms": round(result.timing.retrieve_ms),
            "generate_ms": round(result.timing.generate_ms),
            "judge_ms": round(result.timing.judge_ms),
            "total_ms": round((time.time() - start) * 1000),
        },
    }

    if result.judge_result:
        response["judge"] = {
            "faithfulness": result.judge_result.faithfulness.score,
            "faithfulness_reasoning": result.judge_result.faithfulness.reasoning,
            "relevance": result.judge_result.relevance.score,
            "relevance_reasoning": result.judge_result.relevance.reasoning,
            "passed": result.judge_result.passed,
        }

    return response


async def _stream_answer(question: str, start: float):
    """SSE generator: stream tokens then metadata."""
    import yaml

    # Load config for retrieval
    config_path = Path(_CONFIG_PATH)
    yaml_path = config_path if config_path.suffix in (".yaml", ".yml") else config_path / "config.yaml"
    with open(yaml_path) as f:
        config = yaml.safe_load(f)

    client_name = config["client"]["name"]

    # Run reshape + retrieve first (non-streaming)
    from core.query.reshape import reshape
    from core.query.retrieve import retrieve

    vocab = config.get("reshape", {}).get("vocabulary_hints", [])
    reshaped = await reshape(question, vocabulary_hints=vocab)

    retrieval_cfg = config.get("retrieval", {})
    chunks = await retrieve(
        reshaped.rewritten,
        client_name=client_name,
        top_k=retrieval_cfg.get("top_k", 5),
        rerank=retrieval_cfg.get("rerank", True),
        rerank_top_k=retrieval_cfg.get("rerank_top_k", 3),
    )

    # Load prompt
    prompt_dir = config_path.parent if config_path.is_file() else config_path
    prompt_path = prompt_dir / "prompt.md"
    system_prompt = prompt_path.read_text().strip() if prompt_path.exists() else ""

    # Send evidence chunks first
    evidence_data = [
        {"domain_key": c.get("domain_key"), "kind": c.get("kind"), "content": c.get("content", "")[:200], "score": c.get("score", 0)}
        for c in chunks
    ]
    yield f"event: evidence\ndata: {json.dumps(evidence_data)}\n\n"

    # Stream generation
    gen_cfg = config.get("generation", {})
    full_answer = ""
    async for token in generate_stream(
        query=reshaped.rewritten,
        chunks=chunks,
        system_prompt=system_prompt,
        model=gen_cfg.get("model", "claude-sonnet-4-6"),
        max_tokens=gen_cfg.get("max_tokens", 2048),
    ):
        full_answer += token
        yield f"event: token\ndata: {json.dumps({'text': token})}\n\n"

    # Run judge (non-streaming, after generation completes)
    from core.trust.evals.judge.rubrics import judge

    judge_result = None
    if chunks:
        judge_cfg = config.get("judging", {})
        judge_result = await judge(
            question=reshaped.rewritten,
            answer=full_answer,
            evidence_chunks=[c.get("content", "") for c in chunks],
            model=judge_cfg.get("model", "claude-haiku-4-5-20251001"),
        )

    # Send metadata
    metadata = {
        "route": "no_evidence" if not chunks else "direct",
        "total_ms": round((time.time() - start) * 1000),
    }
    if judge_result:
        metadata["judge"] = {
            "faithfulness": judge_result.faithfulness.score,
            "relevance": judge_result.relevance.score,
            "passed": judge_result.passed,
        }

    yield f"event: done\ndata: {json.dumps(metadata)}\n\n"


@app.get("/traces")
async def traces_endpoint(limit: int = 20):
    """Get recent pipeline traces."""
    return {"traces": get_recent_traces(min(limit, 100))}


@app.get("/traces/{trace_id}")
async def trace_detail_endpoint(trace_id: str):
    """Get a specific trace by ID."""
    t = get_trace(trace_id)
    if t is None:
        return {"error": f"Trace {trace_id} not found"}
    return t


@app.get("/health")
async def health():
    return {"status": "ok", "service": "syntra-rag-core"}


_cached_client_name: str | None = None

def _get_client_name() -> str:
    global _cached_client_name
    if _cached_client_name is None:
        import yaml
        p = Path(_CONFIG_PATH)
        yaml_path = p if p.suffix in (".yaml", ".yml") else p / "config.yaml"
        with open(yaml_path) as f:
            config = yaml.safe_load(f)
        _cached_client_name = config.get("client", {}).get("name", "unknown")
    return _cached_client_name
