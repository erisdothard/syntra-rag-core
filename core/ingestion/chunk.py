"""
core/ingestion/chunk.py — OFFLINE

Generic chunker. Accepts any DomainParser, walks a source directory (or single
file), parses raw files into Chunks, deduplicates, and returns the canonical set.

Contains ZERO domain terms. All domain logic lives in the injected parser.

Build order: Step 3.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

from core.interfaces import Chunk, DomainParser

logger = logging.getLogger(__name__)


def ingest(
    parser: DomainParser,
    source: str | Path,
    *,
    file_glob: str = "*.json",
) -> list[Chunk]:
    """Run the full offline ingestion: parse → dedup → return.

    Args:
        parser:    Any object satisfying the DomainParser protocol.
        source:    Path to a single file or a directory of source files.
        file_glob: Glob pattern when source is a directory. Defaults to *.json.

    Returns:
        Deduplicated list of Chunks, ready for embedding and indexing.
    """
    source = Path(source)

    raw_paths = _resolve_paths(source, file_glob)
    if not raw_paths:
        logger.warning("No files matched source=%s glob=%s", source, file_glob)
        return []

    logger.info("Ingesting %d file(s) from %s", len(raw_paths), source)

    raw_chunks = _parse_all(parser, raw_paths)
    deduped = _dedup(parser, raw_chunks)

    logger.info(
        "Ingestion complete: %d raw chunks → %d after dedup",
        len(raw_chunks),
        len(deduped),
    )
    return deduped


def _resolve_paths(source: Path, file_glob: str) -> list[Path]:
    """Resolve source to a list of files to parse."""
    if source.is_file():
        return [source]
    if source.is_dir():
        paths = sorted(source.glob(file_glob))
        return paths
    logger.warning("Source path does not exist: %s", source)
    return []


def _parse_all(parser: DomainParser, paths: list[Path]) -> list[Chunk]:
    """Parse every file through the injected parser, collecting all chunks."""
    chunks: list[Chunk] = []
    for path in paths:
        try:
            file_chunks = list(parser.parse(str(path)))
            chunks.extend(file_chunks)
            logger.debug("Parsed %s → %d chunks", path.name, len(file_chunks))
        except Exception:
            logger.exception("Parser failed on %s — skipping", path)
    return chunks


def _dedup(parser: DomainParser, chunks: Iterable[Chunk]) -> list[Chunk]:
    """Deduplicate chunks using the parser's dedup_key().

    First occurrence wins. This is intentional — for corpus-style data the
    first canonical example is as good as any other. The parser controls
    what "same" means via dedup_key().
    """
    seen: dict[str, Chunk] = {}
    for chunk in chunks:
        key = parser.dedup_key(chunk)
        if key not in seen:
            seen[key] = chunk
    return list(seen.values())
