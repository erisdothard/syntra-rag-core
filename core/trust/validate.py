"""
core/trust/validate.py

Pydantic v2 base validation models for every artifact that flows through the
pipeline. Industry-neutral — no domain terms.

Three artifact stages, each validated:
  1. ChunkRecord   — a Chunk after ingestion, before or after indexing
  2. RetrievalResult — the set of chunks returned by a query
  3. GenerationResult — the final LLM answer + metadata

Client-specific schemas (in clients/<name>/schema.py) extend these with
domain validation. The core only enforces structural integrity.

Build order: Step 4.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# 1. Chunk validation — runs on every chunk before indexing
# ---------------------------------------------------------------------------


class ChunkRecord(BaseModel):
    """Validated form of a Chunk ready for storage.

    Enforces: content is non-empty, kind is non-empty,
    metadata is a dict. Domain meaning is unchecked — that's
    the client schema's job.
    """

    domain_key: str | None = None
    kind: str
    variant: str | None = None
    content: str
    metadata: dict = Field(default_factory=dict)
    dedup_key: str

    @field_validator("content")
    @classmethod
    def content_not_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Chunk content must not be empty")
        return stripped

    @field_validator("kind")
    @classmethod
    def kind_not_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Chunk kind must not be empty")
        return stripped


# ---------------------------------------------------------------------------
# 2. Retrieval validation — runs on every retrieval result
# ---------------------------------------------------------------------------


class RetrievedChunk(BaseModel):
    """A single chunk returned by the retrieval layer."""

    domain_key: str | None = None
    kind: str
    variant: str | None = None
    content: str
    metadata: dict = Field(default_factory=dict)
    score: float = Field(ge=0.0, le=1.0, description="Relevance score from retrieval")


class RetrievalResult(BaseModel):
    """Validated retrieval output. Enforces non-empty results and score bounds."""

    query: str
    chunks: list[RetrievedChunk]
    total_candidates: int = Field(ge=0, description="Candidates before rerank/filter")

    @field_validator("query")
    @classmethod
    def query_not_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Query must not be empty")
        return stripped


# ---------------------------------------------------------------------------
# 3. Generation validation — runs on every LLM output
# ---------------------------------------------------------------------------


class GenerationResult(BaseModel):
    """Validated generation output. Every answer that leaves the pipeline
    passes through this model before reaching the caller."""

    query: str
    answer: str
    model: str
    chunks_used: list[RetrievedChunk]
    token_usage: TokenUsage | None = None

    @field_validator("answer")
    @classmethod
    def answer_not_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Generated answer must not be empty")
        return stripped


class TokenUsage(BaseModel):
    """Token accounting for cost tracking and observability."""

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


# ---------------------------------------------------------------------------
# Validation runner — the cheap layer that wraps everything
# ---------------------------------------------------------------------------


class ValidationError(Exception):
    """Raised when an artifact fails validation."""

    def __init__(self, stage: str, errors: list[Any]) -> None:
        self.stage = stage
        self.errors = errors
        super().__init__(f"Validation failed at {stage}: {errors}")


def validate_chunk(
    *,
    domain_key: str | None,
    kind: str,
    variant: str | None,
    content: str,
    metadata: dict,
    dedup_key: str,
) -> ChunkRecord:
    """Validate a chunk before indexing. Raises ValidationError on failure."""
    try:
        return ChunkRecord(
            domain_key=domain_key,
            kind=kind,
            variant=variant,
            content=content,
            metadata=metadata,
            dedup_key=dedup_key,
        )
    except Exception as exc:
        raise ValidationError("chunk", [str(exc)]) from exc


def validate_retrieval(
    *,
    query: str,
    chunks: list[dict],
    total_candidates: int,
) -> RetrievalResult:
    """Validate a retrieval result. Raises ValidationError on failure."""
    try:
        return RetrievalResult(
            query=query,
            chunks=[RetrievedChunk(**c) for c in chunks],
            total_candidates=total_candidates,
        )
    except Exception as exc:
        raise ValidationError("retrieval", [str(exc)]) from exc


def validate_generation(
    *,
    query: str,
    answer: str,
    model: str,
    chunks_used: list[dict],
    token_usage: dict | None = None,
) -> GenerationResult:
    """Validate a generation result. Raises ValidationError on failure."""
    try:
        return GenerationResult(
            query=query,
            answer=answer,
            model=model,
            chunks_used=[RetrievedChunk(**c) for c in chunks_used],
            token_usage=TokenUsage(**token_usage) if token_usage else None,
        )
    except Exception as exc:
        raise ValidationError("generation", [str(exc)]) from exc
