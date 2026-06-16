"""
Tests for core/mcp_server.py — MCP tool registration smoke tests.

The FastMCP constructor may differ across versions, so we mock the import
to prevent import-time errors from the source module.
"""

from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest


def _import_mcp_server():
    """Import mcp_server with FastMCP mocked to avoid constructor issues."""
    # Create a mock FastMCP class that records tool registrations
    mock_tool_registry: dict[str, object] = {}

    class MockFastMCP:
        def __init__(self, name: str, **kwargs):
            self.name = name
            self._tools = mock_tool_registry

        def tool(self):
            def decorator(fn):
                mock_tool_registry[fn.__name__] = fn
                return fn
            return decorator

        def run(self):
            pass

    # Patch FastMCP in the mcp.server.fastmcp module
    mock_module = MagicMock()
    mock_module.FastMCP = MockFastMCP

    with patch.dict(sys.modules, {"mcp.server.fastmcp": mock_module, "mcp": MagicMock(), "mcp.server": MagicMock()}):
        # Remove cached module if present
        if "core.mcp_server" in sys.modules:
            del sys.modules["core.mcp_server"]
        import core.mcp_server as mod
        return mod


class TestMCPToolsRegistered:
    """Verify MCP tools are registered on the server."""

    @pytest.fixture(autouse=True)
    def setup_module(self):
        self.mod = _import_mcp_server()
        self.mcp = self.mod.mcp

    def test_server_exists(self):
        assert self.mcp is not None
        assert self.mcp.name == "syntra-rag-core"

    def test_ask_question_tool_registered(self):
        assert "ask_question" in self.mcp._tools

    def test_get_chunk_tool_registered(self):
        assert "get_chunk" in self.mcp._tools

    def test_get_traces_tool_registered(self):
        assert "get_traces" in self.mcp._tools

    def test_get_flagged_tool_registered(self):
        assert "get_flagged" in self.mcp._tools

    def test_get_trace_detail_tool_registered(self):
        assert "get_trace_detail" in self.mcp._tools

    def test_tool_count(self):
        """Exactly 5 tools should be registered."""
        assert len(self.mcp._tools) == 5
