"""Layer 3: real stdio transport smoke — the exact `uv run vtune-mcp` a client executes.

Spawns each console entry point as a subprocess, performs the MCP initialize
handshake, lists tools, and makes one *_check call over the wire.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO_ROOT = Path(__file__).resolve().parent.parent

pytestmark = [pytest.mark.anyio, pytest.mark.slow]


@pytest.mark.parametrize(
    ("entry_point", "server_name", "tool_count"),
    [
        ("vtune-mcp", "vtune", 7),
        ("uprof-mcp", "uprof", 9),  # + uprof_timechart, uprof_system_info
    ],
    ids=["vtune", "uprof"],
)
async def test_stdio_handshake_list_tools_and_check(
    tmp_path: Path, entry_point: str, server_name: str, tool_count: int
) -> None:
    env = {
        **os.environ,
        "PROFILER_MCP_MODE": "mock",
        "PROFILER_MCP_RESULTS_DIR": str(tmp_path / "results"),
    }
    for var in ("MOCK_FAIL", "MOCK_FIXED_TIME", "PROFILER_MCP_TIMEOUT_GRACE"):
        env.pop(var, None)
    params = StdioServerParameters(
        command="uv", args=["run", entry_point], cwd=str(REPO_ROOT), env=env
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        init = await session.initialize()
        assert init.serverInfo.name == server_name

        tools = await session.list_tools()
        names = sorted(t.name for t in tools.tools)
        assert len(names) == tool_count, names
        assert all(name.startswith(f"{server_name}_") for name in names)
        assert f"{server_name}_check" in names
        assert f"{server_name}_compare" in names

        result = await session.call_tool(f"{server_name}_check", {})
        assert not result.isError
        check = result.structuredContent
        assert check["server"] == server_name
        assert check["mode"] == "mock"
        assert check["binary_found"] is True
