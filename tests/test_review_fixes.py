"""Regression tests for the confirmed findings of the adversarial review pass.

Each test names the behavior a reviewer flagged and pins the corrected behavior
so it cannot silently regress. See the review that produced these (docs history)
for the original failure scenarios.
"""

from __future__ import annotations

import pytest

from conftest import call_ok
from profiler_mcp.uprof import server as uprof_server
from profiler_mcp.vtune import server as vtune_server

pytestmark = pytest.mark.anyio

# (server module, collect tool, collect kwargs builder) for the parametrized pairs.
SERVERS = [
    (vtune_server, "vtune", "vtune_collect", "analysis"),
    (uprof_server, "uprof", "uprof_collect", "config"),
]


@pytest.mark.parametrize("mod,prefix,collect,akey", SERVERS)
async def test_crashed_target_surfaces_nonzero_exit(mod, prefix, collect, akey, open_session):
    """A target that exits non-zero must report app_exit_code!=0 and a warning,
    not masquerade as a clean profile (the compare gate depends on this)."""
    async with open_session(mod) as s:
        res = await call_ok(s, collect, {akey: "hotspots", "command": ["sh", "-c", "exit 7"]})
        assert res["app_exit_code"] == 7
        assert any("non-zero" in w or "exited" in w for w in res["warnings"]), res["warnings"]


@pytest.mark.parametrize("mod,prefix,collect,akey", SERVERS)
async def test_empty_report_is_flagged(mod, prefix, collect, akey, open_session, monkeypatch):
    """An empty report (no samples) must carry an explicit note, not read as
    'no hotspots / zero CPU' silently."""
    async with open_session(mod) as s:
        monkeypatch.setenv("MOCK_FAIL", "report-empty")
        res = await call_ok(s, collect, {akey: "hotspots", "command": ["true"]})
        hs = await call_ok(s, f"{prefix}_report_hotspots", {"result_id": res["result_id"]})
        assert hs["rows"] == []
        assert any("empty" in n.lower() for n in hs["notes"]), hs["notes"]


def test_mode_mismatch_raises_for_both_servers(tmp_path):
    """A result collected in one mode cannot be re-read by the other backend."""
    from mcp.server.fastmcp.exceptions import ToolError

    from profiler_mcp.core.config import ServerConfig
    from profiler_mcp.core.store import StoredResult

    for mod, server in ((vtune_server, "vtune"), (uprof_server, "uprof")):
        cfg = ServerConfig(server=server, mode="real", binary="x", argv_prefix=["x"],
                           results_dir=tmp_path)
        entry = StoredResult("hs-0000", "d", server, "hotspots", "mock", "t", "tgt")
        with pytest.raises(ToolError, match="mock.*mode.*real|real.*mock"):
            mod._require_mode_match(cfg, entry)
        # Same mode is fine.
        cfg_mock = ServerConfig(server=server, mode="mock", binary="x", argv_prefix=["x"],
                                results_dir=tmp_path)
        mod._require_mode_match(cfg_mock, entry)  # no raise


async def test_uprof_summary_reports_cpu_time(open_session, workload):
    """uprof_report_summary derives cpu_time_sec from HOTTEST PROCESSES rather
    than hardcoding 0.0."""
    async with open_session(uprof_server) as s:
        c = await call_ok(
            s, "uprof_collect", {"config": "hotspots", "command": [str(workload), "-s", "1"]}
        )
        summ = await call_ok(s, "uprof_report_summary", {"result_id": c["result_id"]})
        assert summ["cpu_time_sec"] > 0.0


async def test_collect_accepts_timeout_sec(open_session, workload):
    """Both collect tools take an explicit timeout_sec (finding: untimed cap)."""
    async with open_session(vtune_server) as s:
        c = await call_ok(
            s, "vtune_collect",
            {"analysis": "hotspots", "command": [str(workload), "-s", "1"], "timeout_sec": 60},
        )
        assert c["result_id"]


async def test_vtune_group_by_module_parses(open_session, workload):
    """group_by=module returns rows keyed by module, not empty (parser + mock)."""
    async with open_session(vtune_server) as s:
        c = await call_ok(
            s, "vtune_collect", {"analysis": "hotspots", "command": [str(workload), "-s", "1"]}
        )
        hs = await call_ok(
            s, "vtune_report_hotspots", {"result_id": c["result_id"], "group_by": "module"}
        )
        assert hs["rows"], "grouped report must not be empty"
        assert all(r["function"] for r in hs["rows"])
