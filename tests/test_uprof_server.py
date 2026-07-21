"""Layer 2: uprof server over in-memory MCP (mock backend, real target process)."""

from __future__ import annotations

import re
import time
from pathlib import Path

import pytest

from conftest import call_err, call_ok
from profiler_mcp.uprof import server as uprof_server

pytestmark = pytest.mark.anyio

# `main` (weight 1) can round to zero samples on short runs, so it may
# legitimately be absent from uProf mock reports.
CORE_FUNCTIONS = {"hot_compute", "hot_memory", "hot_branch"}


async def _collect(session, workload: Path, *extra_args: str, label: str = "") -> dict:
    return await call_ok(
        session,
        "uprof_collect",
        {
            "config": "tbp",
            "command": [str(workload), "--seconds", "0.3", *extra_args],
            "label": label,
        },
    )


async def test_check_reports_mock_mode(open_session) -> None:
    async with open_session(uprof_server) as session:
        result = await call_ok(session, "uprof_check")
        assert result["server"] == "uprof"
        assert result["mode"] == "mock"
        assert result["binary_found"] is True
        assert result["binary"].endswith("uprof_mock.py")
        assert "tbp" in result["available_analyses"]
        assert result["version"] == "5.0.1479.0"
        assert any("synthetic" in note for note in result["notes"])  # mock caveat
        assert any("AMD hardware" in note for note in result["notes"])  # hw caveat


async def test_collect_and_list_results(open_session, workload, results_dir) -> None:
    async with open_session(uprof_server) as session:
        res = await _collect(session, workload, label="baseline")
        assert res["result_id"] == "tbp-0000"
        assert res["analysis"] == "tbp"
        assert res["mode"] == "mock"
        assert res["app_exit_code"] == 0
        assert 0.2 < res["elapsed_sec"] < 30.0
        assert str(workload) in res["target"]
        # result_dir is the timestamped SESSION dir under the per-collect base dir
        session_dir = Path(res["result_dir"])
        assert session_dir.is_dir()
        assert session_dir.parent == results_dir / "uprof" / "tbp-0000"
        assert re.fullmatch(
            r"AMDuProf-hotspots-TBP_[A-Z][a-z]{2}-\d{2}-\d{4}_\d{2}-\d{2}-\d{2}",
            session_dir.name,
        )

        listed = await call_ok(session, "uprof_list_results")
        assert [r["result_id"] for r in listed["results"]] == ["tbp-0000"]
        assert listed["results"][0]["label"] == "baseline"
        assert listed["results"][0]["mode"] == "mock"


async def test_collect_fixed_time_session_dir_is_deterministic(
    open_session, workload, monkeypatch
) -> None:
    fixed = 1750000000  # 2025-06-15T15:06:40Z
    monkeypatch.setenv("MOCK_FIXED_TIME", str(fixed))
    expected_stamp = time.strftime("%b-%d-%Y_%H-%M-%S", time.gmtime(fixed))
    async with open_session(uprof_server) as session:
        res = await _collect(session, workload)
        assert Path(res["result_dir"]).name == f"AMDuProf-hotspots-TBP_{expected_stamp}"


async def test_report_summary(open_session, workload) -> None:
    async with open_session(uprof_server) as session:
        rid = (await _collect(session, workload))["result_id"]
        summary = await call_ok(session, "uprof_report_summary", {"result_id": rid})
        assert summary["result_id"] == rid
        assert summary["analysis"] == "tbp"
        assert 0.2 < summary["elapsed_sec"] < 30.0
        assert summary["metrics"]["duration_sec"] == summary["elapsed_sec"]
        top = summary["top_hotspots"]
        assert top and top[0]["function"] == "hot_compute"
        assert len(top) <= 5
        assert summary["platform_info"]["Target Path"] == str(workload)
        assert any("synthetic" in note for note in summary["notes"])
        assert any("CPU_TIME" in note for note in summary["notes"])  # monitored events


async def test_report_hotspots_top_n_and_sorting(open_session, workload) -> None:
    async with open_session(uprof_server) as session:
        rid = (await _collect(session, workload))["result_id"]

        capped = await call_ok(
            session, "uprof_report_hotspots", {"result_id": rid, "top_n": 2}
        )
        assert len(capped["rows"]) == 2
        assert capped["row_count_total"] in (3, 4)  # `main` may round to 0 samples
        assert capped["truncated"] is True
        assert capped["metric"] == "cpu_time_sec"
        values = [r["value"] for r in capped["rows"]]
        assert values == sorted(values, reverse=True)
        assert capped["rows"][0]["function"] == "hot_compute"
        assert any("synthetic" in note for note in capped["notes"])

        full = await call_ok(session, "uprof_report_hotspots", {"result_id": rid})
        assert full["truncated"] is False
        assert len(full["rows"]) == full["row_count_total"]
        assert {r["function"] for r in full["rows"]} >= CORE_FUNCTIONS

        # ignore_system_modules regenerates the report; the workload is
        # application code, so it must survive the filter.
        nosys = await call_ok(
            session,
            "uprof_report_hotspots",
            {"result_id": rid, "ignore_system_modules": True},
        )
        assert {r["function"] for r in nosys["rows"]} >= CORE_FUNCTIONS


async def test_report_raw_byte_cap_fields(open_session, workload) -> None:
    async with open_session(uprof_server) as session:
        rid = (await _collect(session, workload))["result_id"]
        raw = await call_ok(session, "uprof_report_raw", {"result_id": rid})
        assert raw["result_id"] == rid
        assert "PERFORMANCE ANALYSIS REPORT" in raw["text"]
        assert "HOTTEST FUNCTIONS" in raw["text"]
        assert raw["truncated"] is False
        assert raw["total_bytes"] == len(raw["text"].encode())
        assert "report" in raw["command"]

        # extra_args regenerate into report-raw.csv via the strict mock CLI
        raw2 = await call_ok(
            session, "uprof_report_raw", {"result_id": rid, "extra_args": ["--detail"]}
        )
        assert "--detail" in raw2["command"]
        assert (Path(raw2["command"][raw2["command"].index("--report-output") + 1]).name
                == "report-raw.csv")


async def test_compare_identical_args_pair_passes(open_session, workload) -> None:
    async with open_session(uprof_server) as session:
        base = await _collect(session, workload)
        cand = await _collect(session, workload)
        cmp = await call_ok(
            session,
            "uprof_compare",
            {
                "baseline_id": base["result_id"],
                "candidate_id": cand["result_id"],
                # generous threshold so run-to-run wall jitter can never flake this
                "threshold_pct": 30.0,
            },
        )
        assert cmp["verdict"]["passed"] is True
        assert cmp["metric"] == "cpu_time_sec"
        assert {r["function"] for r in cmp["rows"]} >= CORE_FUNCTIONS
        assert abs(cmp["total_delta_pct"]) < 30.0
        assert any("synthetic" in note for note in cmp["notes"])


async def test_compare_seeded_regression_fails_and_gates(open_session, workload) -> None:
    async with open_session(uprof_server) as session:
        base = await _collect(session, workload)
        cand = await _collect(session, workload, "--only", "compute")

        args = {"baseline_id": base["result_id"], "candidate_id": cand["result_id"]}
        cmp = await call_ok(session, "uprof_compare", {**args, "threshold_pct": 30.0})
        verdict = cmp["verdict"]
        assert verdict["passed"] is False
        assert "regressed" in verdict["reason"]
        rows = {r["function"]: r for r in cmp["rows"]}
        assert rows["hot_compute"]["classification"] == "regression"
        assert rows["hot_compute"]["delta_pct"] > 30.0
        assert rows["hot_memory"]["classification"] == "removed"
        assert rows["hot_branch"]["classification"] == "removed"

        msg = await call_err(
            session,
            "uprof_compare",
            {**args, "threshold_pct": 30.0, "fail_on_regression": True},
        )
        assert "Regression gate failed" in msg
        assert verdict["reason"] in msg


async def test_timechart(open_session, workload, results_dir) -> None:
    async with open_session(uprof_server) as session:
        res = await call_ok(
            session,
            "uprof_timechart",
            {"events": ["power", "temperature"], "duration_sec": 1.0, "interval_ms": 100},
        )
        assert res["result_id"] == "tc-0000"
        assert res["mode"] == "mock"
        assert res["duration_sec"] == 1.0
        assert res["interval_ms"] == 100
        assert res["samples"] == 10  # 1s at 100ms
        assert "core0-power" in res["counters"]
        assert "socket0-temperature" in res["counters"]
        for stats in res["counters"].values():
            assert set(stats) == {"min", "max", "mean", "last"}
            assert stats["min"] <= stats["mean"] <= stats["max"]
        assert any("synthetic" in note for note in res["notes"])
        assert Path(res["result_dir"]).is_dir()

        # timechart results are registered like any other collection
        listed = await call_ok(session, "uprof_list_results")
        entry = {r["result_id"]: r for r in listed["results"]}["tc-0000"]
        assert entry["analysis"] == "timechart"
        assert entry["target"] == "system-wide"


async def test_timechart_interval_below_minimum_rejected(open_session) -> None:
    async with open_session(uprof_server) as session:
        msg = await call_err(
            session,
            "uprof_timechart",
            {"events": ["power"], "duration_sec": 1.0, "interval_ms": 5},
        )
        assert "10 ms" in msg
        msg = await call_err(
            session, "uprof_timechart", {"events": [], "duration_sec": 1.0}
        )
        assert "at least one event" in msg


async def test_system_info(open_session) -> None:
    async with open_session(uprof_server) as session:
        info = await call_ok(session, "uprof_system_info")
        assert info["mode"] == "mock"
        assert info["fields"]["Processor Name"].startswith("AMD Ryzen")
        assert info["fields"]["Number of Cores"] == "6"
        assert info["fields"]["uProf Version"] == "5.0.1479.0"
        assert any("synthetic" in note for note in info["notes"])


async def test_collect_target_validation_errors(open_session, workload) -> None:
    async with open_session(uprof_server) as session:
        msg = await call_err(
            session,
            "uprof_collect",
            {"config": "tbp", "command": [str(workload)], "pid": 4242, "duration_sec": 1},
        )
        assert "exactly one" in msg
        msg = await call_err(session, "uprof_collect", {"config": "tbp"})
        assert "exactly one" in msg
        msg = await call_err(session, "uprof_collect", {"config": "tbp", "pid": 4242})
        assert "duration_sec" in msg


async def test_collect_unknown_config(open_session, workload) -> None:
    async with open_session(uprof_server) as session:
        msg = await call_err(
            session,
            "uprof_collect",
            {"config": "megaperf", "command": [str(workload)]},
        )
        assert "Unknown collect config" in msg
        assert "tbp" in msg  # the known list is offered
        assert "allow_unknown" in msg

        # allow_unknown passes the config straight through; the mock (like the
        # real CLI on a matching machine) accepts it, so the collect succeeds.
        res = await call_ok(
            session,
            "uprof_collect",
            {
                "config": "megaperf",
                "command": [str(workload), "--seconds", "0.3"],
                "allow_unknown": True,
            },
        )
        assert res["analysis"] == "megaperf"
        assert res["result_id"] == "mega-0000"


async def test_unknown_result_id_errors(open_session) -> None:
    async with open_session(uprof_server) as session:
        for tool, args in [
            ("uprof_report_summary", {"result_id": "tbp-9999"}),
            ("uprof_report_hotspots", {"result_id": "tbp-9999"}),
            ("uprof_report_raw", {"result_id": "tbp-9999"}),
            ("uprof_compare", {"baseline_id": "tbp-9999", "candidate_id": "tbp-9998"}),
        ]:
            msg = await call_err(session, tool, args)
            assert "Unknown result_id" in msg
        msg = await call_err(session, "uprof_report_summary", {"result_id": "NOT VALID"})
        assert "Invalid result_id" in msg
