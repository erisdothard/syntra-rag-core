"""
Shared fixtures for the syntra-rag-core test suite.

All external dependencies (Anthropic, Voyage, Supabase) are mocked here
so no real API calls happen in tests.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.interfaces import Chunk

# ---------------------------------------------------------------------------
# Paths to test fixtures
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def sample_config_path() -> Path:
    return FIXTURES_DIR / "test_config.yaml"


@pytest.fixture
def sample_prompt_path() -> Path:
    return FIXTURES_DIR / "test_prompt.md"


@pytest.fixture
def sample_bundle_path() -> Path:
    return FIXTURES_DIR / "sample_bundle.json"


# ---------------------------------------------------------------------------
# Chunk fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_chunk() -> Chunk:
    return Chunk(
        domain_key="CODE-001",
        kind="TestKind",
        variant="test_variant",
        content="This is a test chunk with meaningful content for retrieval.",
        metadata={"source": "test", "version": 1},
    )


@pytest.fixture
def sample_chunks() -> list[Chunk]:
    return [
        Chunk(
            domain_key="CODE-001",
            kind="TypeA",
            variant="variant_x",
            content="First chunk about topic alpha with detail.",
            metadata={"source": "file1.json"},
        ),
        Chunk(
            domain_key="CODE-002",
            kind="TypeB",
            variant="variant_y",
            content="Second chunk describing topic beta in depth.",
            metadata={"source": "file1.json"},
        ),
        Chunk(
            domain_key="CODE-003",
            kind="TypeA",
            variant="variant_z",
            content="Third chunk covering topic gamma thoroughly.",
            metadata={"source": "file2.json"},
        ),
    ]


# ---------------------------------------------------------------------------
# Mock Supabase
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_supabase():
    """Mocked Supabase client. Returns itself for chained method calls."""
    client = MagicMock()

    # .table("chunks").upsert(...).execute()
    execute_result = MagicMock()
    execute_result.data = []
    client.table.return_value.upsert.return_value.execute.return_value = execute_result

    # .table("chunks").select(...).eq(...).eq(...).execute()
    client.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = execute_result

    # .rpc("hybrid_search", {...}).execute()
    rpc_result = MagicMock()
    rpc_result.data = []
    client.rpc.return_value.execute.return_value = rpc_result

    return client


# ---------------------------------------------------------------------------
# Mock Anthropic
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_anthropic():
    """Mocked AsyncAnthropic client with a messages.create stub."""
    client = AsyncMock()

    # Default response shape for messages.create
    content_block = MagicMock()
    content_block.text = '{"rewritten": "improved question", "sub_queries": []}'

    usage = MagicMock()
    usage.input_tokens = 100
    usage.output_tokens = 50

    response = MagicMock()
    response.content = [content_block]
    response.usage = usage

    client.messages.create = AsyncMock(return_value=response)

    return client
