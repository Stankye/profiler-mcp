"""Layer 1: uProf parsers against the VERBATIM vendor fixtures.

Expected values are transcribed from the byte-verified 5.0.1479 captures
(docs/research/captures-uprof.md); a parser change may never edit the fixtures.
"""

from __future__ import annotations

from pathlib import Path

from profiler_mcp.uprof.parse import (
    parse_collect_stdout,
    parse_report_csv,
    parse_timechart_csv,
    parse_version_output,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"

ARGONMD_MODULE = "/home/mdelapierre/proj/bmkg/linux-profiling/argonmd_o2.x"
SESSION_DIR = (
    "/home/mdelapierre/proj/bmkg/amd-profiling/dir_amduprof_o2_gcc_hotspots/"
    "AMDuProf-argonmd_o2_gcc-Hotspots_Jun-09-2025_15-35-29"
)


# -- byte-integrity guards: protect the verbatim capture from editor "fixes" ---


def test_hotspots_fixture_byte_integrity() -> None:
    data = (FIXTURES / "uprof_report_hotspots.csv").read_bytes()
    assert data.startswith(b"\n"), (
        "uprof_report_hotspots.csv must START with a blank line — that lone LF is "
        "part of the byte-verified vendor output, not an accident"
    )
    assert not data.endswith(b"\n"), (
        "uprof_report_hotspots.csv must NOT end with a newline — the real uProf "
        "report.csv has no trailing newline (byte-verified capture)"
    )


# -- hotspots report.csv --------------------------------------------------------


def test_report_hotspots_functions_exact() -> None:
    parsed = parse_report_csv((FIXTURES / "uprof_report_hotspots.csv").read_text())
    funcs = parsed["hottest_functions"]
    assert len(funcs) == 3
    top = funcs[0]
    assert top["function"].startswith("compute_forc_epot(double const*, int, int,")
    assert top["module"] == ARGONMD_MODULE
    assert top["metric"] == "cpu_time_sec"
    assert top["value"] == 4.36
    assert top["percent"] == 80.74  # 4.36 of 5.40 total ≈ 80.7%
    assert top["extra"] == {"inclusive_sec": 4.36}
    assert funcs[1]["function"].startswith("compute_neigh(")
    assert funcs[1]["value"] == 1.03
    assert funcs[2]["function"].startswith("update_pos_pbc(")
    assert funcs[2]["value"] == 0.01
    assert parsed["notes"] == []


def test_report_hotspots_sections() -> None:
    parsed = parse_report_csv((FIXTURES / "uprof_report_hotspots.csv").read_text())
    assert parsed["duration_sec"] == 5.96
    assert parsed["monitored_events"] == ["CPU_TIME"]
    assert parsed["execution"]["Target Path"] == "./argonmd_o2_gcc.x"
    assert parsed["execution"]["CPU Details"] == "Family(0x19), Model(0x44), Number of Cores(12)"
    assert parsed["profile_details"]["Profile Session Type"] == "Hotspots"
    assert parsed["hottest_processes"] == [
        {"name": "argonmd_o2_gcc. (PID:666509)", "value": 5.4}
    ]
    assert parsed["hottest_modules"] == [{"name": ARGONMD_MODULE, "value": 5.4}]
    assert parsed["hottest_threads"] == [
        {"name": "argonmd_o2_gcc. (PID:666509)", "thread_id": "666509", "value": 5.4}
    ]


# -- tbp variant: no Inclusive Time column -------------------------------------


def test_report_tbp_variant_no_inclusive_column() -> None:
    parsed = parse_report_csv((FIXTURES / "uprof_report_tbp.csv").read_text())
    assert parsed["duration_sec"] == 5.708
    funcs = parsed["hottest_functions"]
    assert len(funcs) == 5
    assert funcs[0]["function"].startswith("compute_forc_epot(")
    assert funcs[0]["value"] == 4.245
    assert funcs[0]["percent"] == 81.9
    assert all("extra" not in f for f in funcs)  # tbp reports have no inclusive time
    assert funcs[4] == {
        "function": "do_lookup_x",
        "module": "/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2",
        "metric": "cpu_time_sec",
        "value": 0.001,
        "percent": 0.02,
    }


def test_report_empty_text_is_flagged() -> None:
    parsed = parse_report_csv("")
    assert parsed["hottest_functions"] == []
    assert "report file is empty" in parsed["notes"]


# -- collect stdout ------------------------------------------------------------


def test_collect_stdout_regexes() -> None:
    parsed = parse_collect_stdout((FIXTURES / "uprof_collect_stdout.txt").read_text())
    assert parsed == {"session_dir": SESSION_DIR, "report_path": None}


def test_collect_stdout_report_line() -> None:
    parsed = parse_collect_stdout(
        "Profiling (data collection) completed \n"
        f"Generated data files path: {SESSION_DIR}\n"
        f"Generated report file: {SESSION_DIR}/report.csv\n"
    )
    assert parsed["session_dir"] == SESSION_DIR
    assert parsed["report_path"] == f"{SESSION_DIR}/report.csv"
    assert parse_collect_stdout("") == {"session_dir": None, "report_path": None}


# -- timechart -----------------------------------------------------------------


def test_timechart_counter_stats() -> None:
    parsed = parse_timechart_csv((FIXTURES / "uprof_timechart.csv").read_text())
    assert parsed["samples"] == 3
    assert sorted(parsed["counters"]) == [f"core{i}-power" for i in range(6)]
    assert parsed["counters"]["core0-power"] == {
        "min": 2.1,
        "max": 5.57,
        "mean": 3.2767,  # round((2.10 + 2.16 + 5.57) / 3, 4)
        "last": 5.57,
    }
    assert parsed["details"] == {
        "CPU Details": "Family(0x19) Model(0x44)",
        "Sampling Interval": "100 milli-seconds",
        "Profile Start Time": "Jun-23-2025_12-07-50",
    }


def test_timechart_empty_text_is_safe() -> None:
    parsed = parse_timechart_csv("")
    assert parsed["counters"] == {}
    assert parsed["samples"] == 0


# -- version -------------------------------------------------------------------


def test_parse_version_output() -> None:
    assert parse_version_output("AMDuProfCLI Version 5.0.1479.0\n") == "5.0.1479.0"
    assert parse_version_output("some banner\n4.2.850\n") == "4.2.850"
    assert parse_version_output("") == ""
