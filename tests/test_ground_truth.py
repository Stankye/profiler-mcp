"""Layer 4 ground truth (docs/SELF_TESTING.md): compile -> profile -> attribution.

The full chain against the sidecar oracle (hotspots.mockprofile.json): the
default scenario weights hot_compute at 50/101 of samples, and `--only compute`
shifts it to 95/100. Both servers must attribute accordingly.
"""

from __future__ import annotations

import pytest

from conftest import call_ok
from profiler_mcp.uprof import server as uprof_server
from profiler_mcp.vtune import server as vtune_server

pytestmark = pytest.mark.anyio

SERVERS = [
    pytest.param(vtune_server, "vtune", {"analysis": "hotspots"}, id="vtune"),
    pytest.param(uprof_server, "uprof", {"config": "tbp"}, id="uprof"),
]


def _percent(report: dict, function: str) -> float:
    matches = [r for r in report["rows"] if r["function"] == function]
    assert matches, (
        f"{function} missing from hotspots; got {[r['function'] for r in report['rows']]}"
    )
    return matches[0]["percent"]


async def _hotspots_for(session, prefix: str, target_args: dict, command: list) -> dict:
    collected = await call_ok(session, f"{prefix}_collect", {**target_args, "command": command})
    return await call_ok(
        session, f"{prefix}_report_hotspots", {"result_id": collected["result_id"]}
    )


@pytest.mark.parametrize(("server_module", "prefix", "target_args"), SERVERS)
async def test_default_scenario_attribution(
    open_session, workload, server_module, prefix, target_args
) -> None:
    async with open_session(server_module) as session:
        report = await _hotspots_for(
            session, prefix, target_args, [str(workload), "--seconds", "0.3"]
        )
        # Sidecar model: hot_compute 50, hot_memory 30, hot_branch 20, main 1.
        assert 40.0 <= _percent(report, "hot_compute") <= 60.0
        assert 20.0 <= _percent(report, "hot_memory") <= 40.0
        assert 10.0 <= _percent(report, "hot_branch") <= 30.0
        assert report["rows"][0]["function"] == "hot_compute"  # top hotspot


@pytest.mark.parametrize(("server_module", "prefix", "target_args"), SERVERS)
async def test_only_compute_scenario_attribution(
    open_session, workload, server_module, prefix, target_args
) -> None:
    async with open_session(server_module) as session:
        report = await _hotspots_for(
            session,
            prefix,
            target_args,
            [str(workload), "--seconds", "0.3", "--only", "compute"],
        )
        assert _percent(report, "hot_compute") >= 85.0  # sidecar scenario: 95/100
        assert {r["function"] for r in report["rows"]}.isdisjoint(
            {"hot_memory", "hot_branch"}
        )
