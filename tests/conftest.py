"""Shared fixtures for the profiler-mcp test pyramid (docs/SELF_TESTING.md).

Everything runs in mock mode against an isolated per-test results dir; the
compiled hotspots workload is built once per session (skipped cleanly when the
machine has no C toolchain).
"""

from __future__ import annotations

import shutil
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKLOAD_DIR = REPO_ROOT / "examples" / "workloads"

# Env vars that change server/mock behavior; scrubbed per test so nothing leaks
# from the invoking shell or from a previous test.
_ENV_KNOBS = (
    "MOCK_FAIL",
    "MOCK_FIXED_TIME",
    "PROFILER_MCP_MOCK_BIN",
    "PROFILER_MCP_TIMEOUT_GRACE",
    "VTUNE_MCP_BIN",
    "UPROF_MCP_BIN",
)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "slow: takes more than ~5 seconds (still part of the default run)"
    )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
def workload() -> Path:
    """Compiled examples/workloads/hotspots binary; skips without a C compiler."""
    if shutil.which("make") is None or not any(
        shutil.which(cc) for cc in ("cc", "gcc", "clang")
    ):
        pytest.skip("no C toolchain available to build the hotspots workload")
    build = subprocess.run(
        ["make", "-C", str(WORKLOAD_DIR)], capture_output=True, text=True
    )
    if build.returncode != 0:
        pytest.skip(f"workload build failed: {build.stderr.strip()[:200]}")
    binary = WORKLOAD_DIR / "hotspots"
    smoke = subprocess.run([str(binary), "--seconds", "0.05"], capture_output=True)
    if smoke.returncode != 0:
        # A checked-in binary from another machine/arch can shadow `make`; force once.
        subprocess.run(["make", "-B", "-C", str(WORKLOAD_DIR)], capture_output=True)
        smoke = subprocess.run([str(binary), "--seconds", "0.05"], capture_output=True)
        if smoke.returncode != 0:
            pytest.skip("hotspots workload binary does not run on this machine")
    return binary


@pytest.fixture
def results_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated results base dir + forced mock mode for one test."""
    base = tmp_path / "results"
    monkeypatch.setenv("PROFILER_MCP_RESULTS_DIR", str(base))
    monkeypatch.setenv("PROFILER_MCP_MODE", "mock")
    for var in _ENV_KNOBS:
        monkeypatch.delenv(var, raising=False)
    return base


@pytest.fixture
def open_session(results_dir: Path):
    """Factory: fresh in-memory MCP client session for a given server module.

    Usage: `async with open_session(vtune_server) as session: ...`
    """

    @asynccontextmanager
    async def _open(server_module):
        async with create_connected_server_and_client_session(
            server_module.mcp, raise_exceptions=False
        ) as session:
            yield session

    return _open


async def call_ok(session, tool: str, args: dict | None = None) -> dict:
    """Call a tool, assert success, return its structured content."""
    result = await session.call_tool(tool, args or {})
    detail = result.content[0].text if result.content else "<no content>"
    assert not result.isError, f"{tool} unexpectedly failed: {detail}"
    assert result.structuredContent is not None, f"{tool} returned no structured content"
    return result.structuredContent


async def call_err(session, tool: str, args: dict | None = None) -> str:
    """Call a tool, assert it errored, return the error message text."""
    result = await session.call_tool(tool, args or {})
    assert result.isError, f"{tool} unexpectedly succeeded: {result.structuredContent}"
    assert result.content, f"{tool} errored without any diagnostic content"
    return result.content[0].text
