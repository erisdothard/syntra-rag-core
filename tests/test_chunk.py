"""
Tests for core/ingestion/chunk.py — generic chunker.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable
from unittest.mock import MagicMock

import pytest

from core.ingestion.chunk import _dedup, ingest
from core.interfaces import Chunk, DomainParser


class MockParser:
    """A simple DomainParser for testing. Returns canned chunks."""

    def __init__(self, chunks_per_file: list[Chunk] | None = None):
        self._chunks = chunks_per_file or []

    def parse(self, raw_path: str) -> Iterable[Chunk]:
        return iter(self._chunks)

    def dedup_key(self, chunk: Chunk) -> str:
        return f"{chunk.domain_key or 'none'}|{chunk.variant or 'none'}"


class TestIngest:
    """ingest() orchestrates parse + dedup."""

    def test_with_mock_parser_returns_deduped_chunks(self, tmp_path: Path):
        # Two identical chunks should dedup to one
        chunks = [
            Chunk(domain_key="A", kind="Type1", variant="v1", content="Content A"),
            Chunk(domain_key="A", kind="Type1", variant="v1", content="Content A duplicate"),
            Chunk(domain_key="B", kind="Type2", variant="v2", content="Content B"),
        ]
        parser = MockParser(chunks)

        source_file = tmp_path / "data.json"
        source_file.write_text("{}", encoding="utf-8")

        result = ingest(parser, source_file)
        assert len(result) == 2  # A|v1 deduped, B|v2 kept

    def test_with_empty_directory_returns_empty(self, tmp_path: Path):
        parser = MockParser([])
        result = ingest(parser, tmp_path, file_glob="*.json")
        assert result == []

    def test_with_single_file_works(self, tmp_path: Path):
        chunk = Chunk(domain_key="X", kind="Kind", variant="v", content="Single file chunk")
        parser = MockParser([chunk])

        source_file = tmp_path / "single.json"
        source_file.write_text("{}", encoding="utf-8")

        result = ingest(parser, source_file)
        assert len(result) == 1
        assert result[0].domain_key == "X"

    def test_with_directory_of_files(self, tmp_path: Path):
        chunk = Chunk(domain_key="D", kind="Kind", variant="v", content="Dir chunk")
        parser = MockParser([chunk])

        for i in range(3):
            (tmp_path / f"file_{i}.json").write_text("{}", encoding="utf-8")

        result = ingest(parser, tmp_path, file_glob="*.json")
        # 3 files, each yielding 1 chunk, all same dedup key -> 1 result
        assert len(result) == 1

    def test_nonexistent_source_returns_empty(self):
        parser = MockParser([])
        result = ingest(parser, "/nonexistent/path")
        assert result == []


class TestDedup:
    """_dedup keeps first occurrence when keys collide."""

    def test_keeps_first_occurrence(self):
        parser = MockParser()
        chunks = [
            Chunk(domain_key="A", kind="K", variant="v", content="First"),
            Chunk(domain_key="A", kind="K", variant="v", content="Second (dup)"),
        ]
        result = _dedup(parser, chunks)
        assert len(result) == 1
        assert result[0].content == "First"

    def test_no_duplicates_keeps_all(self):
        parser = MockParser()
        chunks = [
            Chunk(domain_key="A", kind="K", variant="v1", content="One"),
            Chunk(domain_key="B", kind="K", variant="v2", content="Two"),
            Chunk(domain_key="C", kind="K", variant="v3", content="Three"),
        ]
        result = _dedup(parser, chunks)
        assert len(result) == 3

    def test_empty_input_returns_empty(self):
        parser = MockParser()
        result = _dedup(parser, [])
        assert result == []
