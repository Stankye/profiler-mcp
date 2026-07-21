"""Fault injection via MOCK_FAIL: every error path is first-class tested behavior.

The mocks simulate the documented failure modes (docs/SELF_TESTING.md): permission
refusals with vendor-shaped text, nonzero exits after normal-looking output, empty
report files, and wedged collections that must hit the server timeout.
"""

from __future__ import annotations

import pytest

from conftest import call_err, call_ok
from profiler_mcp.uprof import server as uprof_server
from profiler_mcp.vtune import server as vtune_server

pytestmark = pytest.mark.anyio


def _vtune_collect_args(workload) -> dict:
    return {"analysis": "hotspots", "command": [str(workload), "--seconds", "0.2"]}


def _uprof_collect_args(workload) -> dict:
    return {"config": "tbp", "command": [str(workload), "--seconds", "0.2"]}


# -- collect-perm: vendor-shaped permission refusals ---------------------------


async def test_collect_perm_vtune(open_session, workload, monkeypatch) -> None:
    monkeypatch.setenv("MOCK_FAIL", "collect-perm")
    async with open_session(vtune_server) as session:
        msg = await call_err(session, "vtune_collect", _vtune_collect_args(workload))
        assert "Install Intel Sampling Drivers" in msg  # verbatim vendor error text
        assert "perf_event_paranoid" in msg


async def test_collect_perm_uprof(open_session, workload, monkeypatch) -> None:
    monkeypatch.setenv("MOCK_FAIL", "collect-perm")
    async with open_session(uprof_server) as session:
        msg = await call_err(session, "uprof_collect", _uprof_collect_args(workload))
        assert "perf_event_open syscall failed" in msg
        assert "Permission denied" in msg


# -- bad-exit: nonzero exit after normal-looking output ------------------------


async def test_bad_exit_vtune(open_session, workload, monkeypatch) -> None:
    monkeypatch.setenv("MOCK_FAIL", "bad-exit")
    async with open_session(vtune_server) as session:
        msg = await call_err(session, "vtune_collect", _vtune_collect_args(workload))
        assert "exit 41" in msg  # the exit code is surfaced, not swallowed


async def test_bad_exit_uprof(open_session, workload, monkeypatch) -> None:
    monkeypatch.setenv("MOCK_FAIL", "bad-exit")
    async with open_session(uprof_server) as session:
        msg = await call_err(session, "uprof_collect", _uprof_collect_args(workload))
        assert "exit 41" in msg


# -- report-empty: truncated/empty report files --------------------------------
# The reports must not fabricate a normal-looking result: either an actionable
# error, or an unmistakably empty result (zero rows, zero totals, flagged notes).


async def test_report_empty_vtune(open_session, workload, monkeypatch) -> None:
    async with open_session(vtune_server) as session:
        rid = (await call_ok(session, "vtune_collect", _vtune_collect_args(workload)))[
            "result_id"
        ]
        monkeypatch.setenv("MOCK_FAIL", "report-empty")

        hotspots = await call_ok(session, "vtune_report_hotspots", {"result_id": rid})
        assert hotspots["rows"] == []  # empty is visibly empty...
        assert hotspots["row_count_total"] == 0
        assert hotspots["total_value"] == 0.0
        assert hotspots["truncated"] is False  # ...not silently truncated

        summary = await call_ok(session, "vtune_report_summary", {"result_id": rid})
        assert summary["top_hotspots"] == []
        assert summary["elapsed_sec"] == 0.0
        assert summary["cpu_time_sec"] == 0.0
        assert summary["metrics"] == {}


async def test_report_empty_uprof(open_session, workload, monkeypatch) -> None:
    async with open_session(uprof_server) as session:
        rid = (await call_ok(session, "uprof_collect", _uprof_collect_args(workload)))[
            "result_id"
        ]
        monkeypatch.setenv("MOCK_FAIL", "report-empty")

        summary = await call_ok(session, "uprof_report_summary", {"result_id": rid})
        assert summary["top_hotspots"] == []
        assert summary["elapsed_sec"] == 0.0
        assert any("empty" in note for note in summary["notes"])  # explicitly flagged

        hotspots = await call_ok(session, "uprof_report_hotspots", {"result_id": rid})
        assert hotspots["rows"] == []
        assert hotspots["row_count_total"] == 0
        assert hotspots["total_value"] == 0.0


# -- collect-hang: wedged collection must hit the server timeout ---------------
# PROFILER_MCP_TIMEOUT_GRACE=1 + duration_sec=1 gives a 2s deadline per test.


async def test_collect_hang_times_out_vtune(open_session, workload, monkeypatch) -> None:
    monkeypatch.setenv("MOCK_FAIL", "collect-hang")
    monkeypatch.setenv("PROFILER_MCP_TIMEOUT_GRACE", "1")
    async with open_session(vtune_server) as session:
        msg = await call_err(
            session,
            "vtune_collect",
            {**_vtune_collect_args(workload), "duration_sec": 1},
        )
        assert "timed out" in msg
        assert "2s" in msg  # duration + grace


async def test_collect_hang_times_out_uprof(open_session, workload, monkeypatch) -> None:
    monkeypatch.setenv("MOCK_FAIL", "collect-hang")
    monkeypatch.setenv("PROFILER_MCP_TIMEOUT_GRACE", "1")
    async with open_session(uprof_server) as session:
        msg = await call_err(
            session,
            "uprof_collect",
            {**_uprof_collect_args(workload), "duration_sec": 1},
        )
        assert "timed out" in msg
        assert "2s" in msg
