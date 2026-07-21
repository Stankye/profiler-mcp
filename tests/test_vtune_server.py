"""Layer 2: vtune server over in-memory MCP (mock backend, real target process)."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import call_err, call_ok
from profiler_mcp.vtune import server as vtune_server

pytestmark = pytest.mark.anyio

WORKLOAD_FUNCTIONS = {"hot_compute", "hot_memory", "hot_branch", "main"}


async def _collect(session, workload: Path, *extra_args: str, label: str = "") -> dict:
    return await call_ok(
        session,
        "vtune_collect",
        {
            "analysis": "hotspots",
            "command": [str(workload), "--seconds", "0.3", *extra_args],
            "label": label,
        },
    )


async def test_check_reports_mock_mode(open_session) -> None:
    async with open_session(vtune_server) as session:
        result = await call_ok(session, "vtune_check")
        assert result["server"] == "vtune"
        assert result["mode"] == "mock"
        assert result["binary_found"] is True
        assert result["binary"].endswith("vtune_mock.py")
        assert "hotspots" in result["available_analyses"]
        assert result["version"].startswith("Intel(R) VTune(TM) Profiler")
        assert any("synthetic" in note for note in result["notes"])  # mock caveat


async def test_collect_and_list_results(open_session, workload, results_dir) -> None:
    async with open_session(vtune_server) as session:
        res = await _collect(session, workload, label="baseline")
        assert res["result_id"] == "hs-0000"
        assert res["analysis"] == "hotspots"
        assert res["mode"] == "mock"
        assert res["app_exit_code"] == 0
        assert 0.2 < res["elapsed_sec"] < 30.0
        assert str(workload) in res["target"]
        rdir = Path(res["result_dir"])
        assert rdir == results_dir / "vtune" / "hs-0000"
        assert rdir.is_dir()

        listed = await call_ok(session, "vtune_list_results")
        assert [r["result_id"] for r in listed["results"]] == ["hs-0000"]
        entry = listed["results"][0]
        assert entry["mode"] == "mock"
        assert entry["label"] == "baseline"
        assert entry["analysis"] == "hotspots"


async def test_report_summary(open_session, workload) -> None:
    async with open_session(vtune_server) as session:
        rid = (await _collect(session, workload))["result_id"]
        summary = await call_ok(session, "vtune_report_summary", {"result_id": rid})
        assert summary["result_id"] == rid
        assert summary["analysis"] == "hotspots"
        assert 0.2 < summary["elapsed_sec"] < 30.0
        assert summary["cpu_time_sec"] > 0.0
        top = summary["top_hotspots"]
        assert top and top[0]["function"] == "hot_compute"
        assert {r["function"] for r in top} <= WORKLOAD_FUNCTIONS | {"[Others]"}
        assert summary["platform_info"]  # collection/platform section parsed
        assert any("synthetic" in note for note in summary["notes"])


async def test_report_hotspots_top_n_and_sorting(open_session, workload) -> None:
    async with open_session(vtune_server) as session:
        rid = (await _collect(session, workload))["result_id"]

        capped = await call_ok(
            session, "vtune_report_hotspots", {"result_id": rid, "top_n": 2}
        )
        assert len(capped["rows"]) == 2
        assert capped["row_count_total"] == 4
        assert capped["truncated"] is True
        assert capped["metric"] == "cpu_time_sec"
        values = [r["value"] for r in capped["rows"]]
        assert values == sorted(values, reverse=True)
        assert capped["rows"][0]["function"] == "hot_compute"
        assert any("synthetic" in note for note in capped["notes"])

        full = await call_ok(session, "vtune_report_hotspots", {"result_id": rid})
        assert full["truncated"] is False
        assert len(full["rows"]) == full["row_count_total"] == 4
        assert {r["function"] for r in full["rows"]} == WORKLOAD_FUNCTIONS
        assert full["total_value"] == pytest.approx(
            sum(r["value"] for r in full["rows"]), rel=1e-6
        )


async def test_report_raw_byte_cap_fields(open_session, workload) -> None:
    async with open_session(vtune_server) as session:
        rid = (await _collect(session, workload))["result_id"]
        raw = await call_ok(
            session, "vtune_report_raw", {"result_id": rid, "report_type": "summary"}
        )
        assert raw["result_id"] == rid
        assert "Elapsed Time" in raw["text"]
        assert "Top Hotspots" in raw["text"]
        assert raw["truncated"] is False
        assert raw["total_bytes"] == len(raw["text"].encode())
        assert "-report" in raw["command"]
        assert "summary" in raw["command"]

        # Unknown report types are rejected up front...
        msg = await call_err(
            session, "vtune_report_raw", {"result_id": rid, "report_type": "starfield"}
        )
        assert "Unknown report type" in msg
        assert "allow_unknown" in msg
        # ...and with allow_unknown the strict mock CLI rejects them instead.
        msg = await call_err(
            session,
            "vtune_report_raw",
            {"result_id": rid, "report_type": "starfield", "allow_unknown": True},
        )
        assert "Cannot find report" in msg


async def test_compare_identical_args_pair_passes(open_session, workload) -> None:
    async with open_session(vtune_server) as session:
        base = await _collect(session, workload)
        cand = await _collect(session, workload)
        assert base["result_id"] != cand["result_id"]
        cmp = await call_ok(
            session,
            "vtune_compare",
            {
                "baseline_id": base["result_id"],
                "candidate_id": cand["result_id"],
                # generous threshold: wall-clock jitter between two real runs must
                # never flake this; the regression test below still fails hard
                "threshold_pct": 30.0,
            },
        )
        assert cmp["verdict"]["passed"] is True
        assert cmp["metric"] == "cpu_time_sec"
        assert {r["function"] for r in cmp["rows"]} == WORKLOAD_FUNCTIONS
        assert abs(cmp["total_delta_pct"]) < 30.0
        assert any("synthetic" in note for note in cmp["notes"])


async def test_compare_seeded_regression_fails_and_gates(open_session, workload) -> None:
    async with open_session(vtune_server) as session:
        base = await _collect(session, workload)
        cand = await _collect(session, workload, "--only", "compute")

        args = {"baseline_id": base["result_id"], "candidate_id": cand["result_id"]}
        cmp = await call_ok(session, "vtune_compare", {**args, "threshold_pct": 30.0})
        verdict = cmp["verdict"]
        assert verdict["passed"] is False
        assert "regressed" in verdict["reason"]
        assert verdict["worst_regression_pct"] > 30.0
        rows = {r["function"]: r for r in cmp["rows"]}
        # hot_compute jumps 50% -> 95% of the run: a large regression
        assert rows["hot_compute"]["classification"] == "regression"
        assert rows["hot_compute"]["delta_pct"] > 30.0
        # the other phases vanish from the candidate entirely
        assert rows["hot_memory"]["classification"] == "removed"
        assert rows["hot_branch"]["classification"] == "removed"

        # fail_on_regression turns the failing verdict into a hard ToolError
        # carrying the same reason (the agentic-loop gate).
        msg = await call_err(
            session,
            "vtune_compare",
            {**args, "threshold_pct": 30.0, "fail_on_regression": True},
        )
        assert "Regression gate failed" in msg
        assert verdict["reason"] in msg


async def test_collect_target_validation_errors(open_session, workload) -> None:
    async with open_session(vtune_server) as session:
        # both command and pid
        msg = await call_err(
            session,
            "vtune_collect",
            {
                "analysis": "hotspots",
                "command": [str(workload)],
                "pid": 4242,
                "duration_sec": 1,
            },
        )
        assert "exactly one" in msg
        # neither command nor pid
        msg = await call_err(session, "vtune_collect", {"analysis": "hotspots"})
        assert "exactly one" in msg
        # pid without duration
        msg = await call_err(session, "vtune_collect", {"analysis": "hotspots", "pid": 4242})
        assert "duration_sec" in msg


async def test_collect_unknown_analysis(open_session, workload) -> None:
    async with open_session(vtune_server) as session:
        msg = await call_err(
            session,
            "vtune_collect",
            {"analysis": "quantum-vibes", "command": [str(workload)]},
        )
        assert "Unknown analysis type" in msg
        assert "hotspots" in msg  # the known list is offered
        assert "allow_unknown" in msg

        # allow_unknown bypasses OUR validation; the strict mock CLI still
        # rejects it, proving the flag is passed through untouched.
        msg = await call_err(
            session,
            "vtune_collect",
            {
                "analysis": "quantum-vibes",
                "command": [str(workload), "--seconds", "0.1"],
                "allow_unknown": True,
            },
        )
        assert "Cannot find analysis type" in msg


async def test_unknown_result_id_errors(open_session) -> None:
    async with open_session(vtune_server) as session:
        for tool, args in [
            ("vtune_report_summary", {"result_id": "hs-9999"}),
            ("vtune_report_hotspots", {"result_id": "hs-9999"}),
            ("vtune_report_raw", {"result_id": "hs-9999", "report_type": "summary"}),
            ("vtune_compare", {"baseline_id": "hs-9999", "candidate_id": "hs-9998"}),
        ]:
            msg = await call_err(session, tool, args)
            assert "Unknown result_id" in msg
        msg = await call_err(session, "vtune_report_summary", {"result_id": "NOT VALID"})
        assert "Invalid result_id" in msg
