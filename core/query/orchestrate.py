"""
core/query/orchestrate.py — LIVE

Route to the simplest capability that answers. Escalate only when proven
necessary. This is the single entry point for the live query pipeline.

Pipeline: reshape → retrieve → generate → validate → (optional) judge

Routing logic (simplest first):
  1. DIRECT — retrieval returns high-confidence chunks → generate immediately
  2. DECOMPOSED — reshape split the query → retrieve per sub-query, merge, generate
  3. NO_EVIDENCE — nothing retrieved → return a grounded "I don't know"

The orchestrator does NOT escalate to agents, tools, or multi-step planning.
That would be an agentic layer built ON TOP of this pipeline. This module
stays a simple router.

Build order: Step 8.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from core.query.generate import generate
from core.query.reshape import ReshapedQuery, reshape
from core.query.retrieve import retrieve
from core.trust.evals.judge.rubrics import JudgeResult, judge
from core.trust.validate import GenerationResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StageTiming:
    """Per-stage wall-clock timing."""
    reshape_ms: float = 0.0
    retrieve_ms: float = 0.0
    generate_ms: float = 0.0
    judge_ms: float = 0.0


@dataclass(frozen=True)
class OrchestratorResult:
    """Full pipeline output including routing metadata."""

    route: str  # "direct", "decomposed", "no_evidence"
    generation: GenerationResult
    judge_result: JudgeResult | None  # None if judging was skipped
    reshaped_query: ReshapedQuery
    timing: StageTiming = field(default_factory=StageTiming)


async def ask(
    question: str,
    *,
    config_path: str | Path,
) -> OrchestratorResult:
    """End-to-end: question in → grounded answer out.

    Args:
        question:    Raw user question.
        config_path: Path to client config.yaml.

    Returns:
        OrchestratorResult with the answer, route taken, and optional judge score.
    """
    config = _load_config(config_path)

    client_name = config["client"]["name"]
    system_prompt = _load_prompt(config_path)

    # -- Reshape --
    t0 = time.perf_counter()
    vocab = config.get("reshape", {}).get("vocabulary_hints", [])
    reshape_model = config.get("reshape", {}).get("model", "claude-haiku-4-5-20251001")
    reshaped = await reshape(question, vocabulary_hints=vocab, model=reshape_model)
    reshape_ms = (time.perf_counter() - t0) * 1000

    # -- Retrieve --
    t0 = time.perf_counter()
    retrieval_cfg = config.get("retrieval", {})
    top_k = retrieval_cfg.get("top_k", 5)
    do_rerank = retrieval_cfg.get("rerank", True)
    rerank_top_k = retrieval_cfg.get("rerank_top_k", 3)

    if reshaped.sub_queries:
        chunks = await _retrieve_decomposed(
            sub_queries=reshaped.sub_queries,
            client_name=client_name,
            top_k=top_k,
            rerank=do_rerank,
            rerank_top_k=rerank_top_k,
        )
        route = "decomposed"
    else:
        chunks = await retrieve(
            reshaped.rewritten,
            client_name=client_name,
            top_k=top_k,
            rerank=do_rerank,
            rerank_top_k=rerank_top_k,
        )
        route = "direct"

    if not chunks:
        route = "no_evidence"
    retrieve_ms = (time.perf_counter() - t0) * 1000

    # -- Generate --
    t0 = time.perf_counter()
    gen_cfg = config.get("generation", {})
    gen_model = gen_cfg.get("model", "claude-sonnet-4-6")
    max_tokens = gen_cfg.get("max_tokens", 2048)
    temperature = gen_cfg.get("temperature", 0.0)

    generation = await generate(
        query=reshaped.rewritten,
        chunks=chunks,
        system_prompt=system_prompt,
        model=gen_model,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    generate_ms = (time.perf_counter() - t0) * 1000

    # -- Judge (selective — only when we have evidence) --
    t0 = time.perf_counter()
    judge_result = None
    if route != "no_evidence":
        judge_cfg = config.get("judging", {})
        judge_model = judge_cfg.get("model", "claude-haiku-4-5-20251001")
        f_threshold = judge_cfg.get("faithfulness", {}).get("threshold", 3)
        r_threshold = judge_cfg.get("relevance", {}).get("threshold", 3)

        judge_result = await judge(
            question=reshaped.rewritten,
            answer=generation.answer,
            evidence_chunks=[c.get("content", "") for c in chunks],
            model=judge_model,
            faithfulness_threshold=f_threshold,
            relevance_threshold=r_threshold,
        )

        if not judge_result.passed:
            logger.warning(
                "Judge flagged answer: faithfulness=%d relevance=%d",
                judge_result.faithfulness.score,
                judge_result.relevance.score,
            )
    judge_ms = (time.perf_counter() - t0) * 1000

    timing = StageTiming(
        reshape_ms=reshape_ms,
        retrieve_ms=retrieve_ms,
        generate_ms=generate_ms,
        judge_ms=judge_ms,
    )

    logger.info(
        "Orchestrator complete: route=%s judged=%s reshape=%.0fms retrieve=%.0fms generate=%.0fms judge=%.0fms",
        route, judge_result is not None,
        reshape_ms, retrieve_ms, generate_ms, judge_ms,
    )

    return OrchestratorResult(
        route=route,
        generation=generation,
        judge_result=judge_result,
        reshaped_query=reshaped,
        timing=timing,
    )


# ---------------------------------------------------------------------------
# Decomposed retrieval — merge results from multiple sub-queries
# ---------------------------------------------------------------------------


async def _retrieve_decomposed(
    *,
    sub_queries: list[str],
    client_name: str,
    top_k: int,
    rerank: bool,
    rerank_top_k: int,
) -> list[dict[str, Any]]:
    """Retrieve for each sub-query in parallel, merge, deduplicate."""
    # Run all sub-queries concurrently
    tasks = [
        retrieve(
            sq,
            client_name=client_name,
            top_k=top_k,
            rerank=rerank,
            rerank_top_k=rerank_top_k,
        )
        for sq in sub_queries
    ]
    all_results = await asyncio.gather(*tasks)

    seen_ids: set[str] = set()
    merged: list[dict[str, Any]] = []
    for results in all_results:
        for r in results:
            rid = r.get("id", r.get("domain_key", ""))
            if rid and rid not in seen_ids:
                seen_ids.add(rid)
                merged.append(r)

    merged.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    return merged[:top_k]


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


_config_cache: dict[str, dict] = {}
_prompt_cache: dict[str, str] = {}


def _load_config(config_path: str | Path) -> dict:
    """Load the client's config.yaml (cached after first read)."""
    key = str(config_path)
    if key not in _config_cache:
        p = Path(config_path)
        yaml_path = p if p.suffix in (".yaml", ".yml") else p / "config.yaml"
        with open(yaml_path, "r", encoding="utf-8") as f:
            _config_cache[key] = yaml.safe_load(f)
    return _config_cache[key]


def _load_prompt(config_path: str | Path) -> str:
    """Load the client's system prompt from prompt.md (cached after first read)."""
    key = str(config_path)
    if key not in _prompt_cache:
        p = Path(config_path)
        prompt_dir = p.parent if p.is_file() else p
        prompt_path = prompt_dir / "prompt.md"
        if not prompt_path.exists():
            logger.warning("No prompt.md found at %s — using empty system prompt", prompt_path)
            _prompt_cache[key] = ""
        else:
            _prompt_cache[key] = prompt_path.read_text(encoding="utf-8").strip()
    return _prompt_cache[key]
