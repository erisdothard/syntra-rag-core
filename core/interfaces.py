"""
core/interfaces.py

The seam between core and clients.

Defines:
- Chunk: the universal data unit that flows through the entire pipeline.
- DomainParser: the protocol every client must implement to feed data into the core.

This file is industry-neutral. No domain terms. Clients give meaning to
domain_key, kind, variant, and metadata — the core never interprets them.
"""

from __future__ import annotations

from typing import Iterable, Protocol

from pydantic import BaseModel, Field


class Chunk(BaseModel):
    """A single retrievable unit of knowledge.

    The core treats these fields as opaque labels. Only the client
    that created the chunk knows what domain_key or kind actually mean.
    """

    domain_key: str | None = Field(
        default=None,
        description="Client-defined primary key for dedup and lookup.",
    )
    kind: str = Field(
        description="Client-defined type label for the source record.",
    )
    variant: str | None = Field(
        default=None,
        description="Client-defined sub-type when the same kind has structural variants.",
    )
    content: str = Field(
        description="Human-readable text that gets embedded and retrieved.",
    )
    metadata: dict = Field(
        default_factory=dict,
        description="Arbitrary client-specific context. Stored as jsonb, never interpreted by core.",
    )


class DomainParser(Protocol):
    """Interface every client must implement.

    parse():      reads raw source files and yields Chunks.
    dedup_key():  returns a string key used to deduplicate chunks during ingestion.
                  Two chunks with the same dedup_key are considered duplicates;
                  only one is kept.
    """

    def parse(self, raw_path: str) -> Iterable[Chunk]:
        """Parse a single source file and yield Chunks."""
        ...

    def dedup_key(self, chunk: Chunk) -> str:
        """Return a dedup key for the given chunk."""
        ...
