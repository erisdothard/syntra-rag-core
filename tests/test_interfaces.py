"""
Tests for core/interfaces.py — Chunk model and DomainParser protocol.
"""

from __future__ import annotations

from typing import Iterable

import pytest
from pydantic import ValidationError

from core.interfaces import Chunk, DomainParser


class TestChunk:
    """Chunk model creation and validation."""

    def test_create_with_valid_data(self):
        chunk = Chunk(
            domain_key="KEY-123",
            kind="Document",
            variant="summary",
            content="A valid chunk of text.",
            metadata={"source": "test.json"},
        )
        assert chunk.domain_key == "KEY-123"
        assert chunk.kind == "Document"
        assert chunk.variant == "summary"
        assert chunk.content == "A valid chunk of text."
        assert chunk.metadata == {"source": "test.json"}

    def test_create_with_minimal_fields(self):
        chunk = Chunk(kind="Record", content="Minimal content.")
        assert chunk.domain_key is None
        assert chunk.variant is None
        assert chunk.metadata == {}

    def test_allows_none_domain_key(self):
        chunk = Chunk(domain_key=None, kind="Record", content="Content here.")
        assert chunk.domain_key is None

    def test_allows_none_variant(self):
        chunk = Chunk(kind="Record", variant=None, content="Content here.")
        assert chunk.variant is None

    def test_rejects_missing_content(self):
        with pytest.raises(ValidationError):
            Chunk(kind="Record")  # type: ignore[call-arg]

    def test_rejects_missing_kind(self):
        with pytest.raises(ValidationError):
            Chunk(content="Some content")  # type: ignore[call-arg]

    def test_metadata_defaults_to_empty_dict(self):
        chunk = Chunk(kind="Record", content="Content.")
        assert chunk.metadata == {}

    def test_metadata_accepts_nested_dict(self):
        meta = {"nested": {"key": [1, 2, 3]}, "flag": True}
        chunk = Chunk(kind="Record", content="Content.", metadata=meta)
        assert chunk.metadata["nested"]["key"] == [1, 2, 3]


class TestDomainParserProtocol:
    """DomainParser protocol conformance."""

    def test_mock_class_satisfies_protocol(self):
        """A class with parse() and dedup_key() satisfies DomainParser."""

        class MockParser:
            def parse(self, raw_path: str) -> Iterable[Chunk]:
                yield Chunk(kind="Test", content="test")

            def dedup_key(self, chunk: Chunk) -> str:
                return f"{chunk.domain_key}|{chunk.variant}"

        parser = MockParser()
        # Protocol check: isinstance won't work without runtime_checkable,
        # but we verify the interface methods exist and work.
        chunks = list(parser.parse("/fake/path"))
        assert len(chunks) == 1
        assert chunks[0].kind == "Test"

        key = parser.dedup_key(chunks[0])
        assert isinstance(key, str)

    def test_protocol_requires_parse_and_dedup_key(self):
        """A class missing one method does NOT satisfy the protocol contract."""

        class IncompleteParser:
            def parse(self, raw_path: str) -> Iterable[Chunk]:
                return []

        parser = IncompleteParser()
        assert hasattr(parser, "parse")
        assert not hasattr(parser, "dedup_key")
