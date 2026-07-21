"""Layer 1: VTune parsers against the VERBATIM vendor fixtures.

Expected values are transcribed from the captures themselves
(docs/research/captures-vtune.md); a parser change may never edit the fixtures.
"""

from __future__ import annotations

from pathlib import Path

from profiler_mcp.vtune.parse import (
    parse_hotspots_csv,
    parse_summary_text,
    parse_version_output,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


# -- summary: 2025 4-column variant -------------------------------------------


def test_summary_2025_headline_times() -> None:
    parsed = parse_summary_text((FIXTURES / "vtune_summary_2025.txt").read_text())
    assert parsed["elapsed_sec"] == 1.307
    assert parsed["cpu_time_sec"] == 16.663


def test_summary_2025_top_hotspots_table() -> None:
    parsed = parse_summary_text((FIXTURES / "vtune_summary_2025.txt").read_text())
    top = parsed["top_hotspots"]
    assert len(top) == 6  # 5 functions + [Others]
    assert top[0] == {
        "function": "func@0x1fe10",
        "module": "libgomp.so.1",
        "metric": "cpu_time_sec",
        "value": 6.021,
        "percent": 36.1,  # taken from the '% of CPU Time(%)' column, not recomputed
    }
    assert top[2]["function"] == "heat_flow._omp_fn.0"
    assert top[2]["module"] == "heat_flow"
    assert top[2]["value"] == 4.46
    assert top[-1] == {
        "function": "[Others]",
        "module": "N/A",
        "metric": "cpu_time_sec",
        "value": 0.02,
        "percent": 0.1,
    }


def test_summary_2025_metrics_and_platform() -> None:
    parsed = parse_summary_text((FIXTURES / "vtune_summary_2025.txt").read_text())
    assert parsed["metrics"] == {
        "Effective Time": 16.663,
        "Spin Time": 0.0,
        "Overhead Time": 0.0,
        "Total Thread Count": 16.0,
        "Paused Time": 0.0,
    }
    platform = parsed["platform_info"]
    assert platform["Application Command Line"] == './heat_flow "2048" "16"'
    assert platform["Computer Name"] == "d0143"
    assert platform["Collector Type"] == "User-mode sampling and tracing"
    # Nested blocks are flattened with their block-name prefix.
    assert platform["CPU Name"] == "Unknown"
    assert platform["CPU Frequency"] == "1.996 GHz"
    assert platform["CPU Logical CPU Count"] == "128"
    assert platform["CPU Cache Allocation Technology Level 2 capability"] == "not detected"
    assert platform["CPU Cache Allocation Technology Level 3 capability"] == "available"
    assert parsed["notes"] == []  # the trailing hint block is not a note


# -- summary: 2021 3-column variant -------------------------------------------


def test_summary_2021_no_elapsed_percent_computed() -> None:
    parsed = parse_summary_text((FIXTURES / "vtune_summary_2021.txt").read_text())
    assert parsed["elapsed_sec"] is None  # 2021 capture has no Elapsed Time line
    assert parsed["cpu_time_sec"] == 7.41
    top = parsed["top_hotspots"]
    assert len(top) == 6
    assert top[0]["function"] == "PageRankPullGS._omp_fn.1"
    assert top[0]["module"] == "pr"
    assert top[0]["value"] == 5.678
    assert top[0]["percent"] == 76.62  # no percent column: computed from the total
    assert top[1]["function"] == "std::istream::operator>>"
    assert top[-1]["function"] == "[Others]"


def test_summary_2021_issue_block_becomes_note() -> None:
    parsed = parse_summary_text((FIXTURES / "vtune_summary_2021.txt").read_text())
    assert parsed["metrics"]["Effective Physical Core Utilization"] == 6.3
    assert parsed["metrics"]["Poor"] == 7.41
    assert len(parsed["notes"]) == 1
    note = parsed["notes"][0]
    assert note.startswith("Effective Physical Core Utilization:")
    assert "load imbalance" in note


# -- hotspots CSV: TAB default delimiter --------------------------------------


def test_hotspots_tab_csv_exact_rows() -> None:
    rows = parse_hotspots_csv((FIXTURES / "vtune_hotspots_tab.csv").read_text())
    assert len(rows) == 3
    assert rows[0] == {
        "function": "ComputeSYMGS_ref",
        "module": "xhpcg",
        "metric": "cpu_time_sec",
        "value": 47.479808,
        "percent": 69.88,
        "extra": {
            "effective_time_sec": 47.479808,
            "spin_time_sec": 0.0,
            "overhead_time_sec": 0.0,
        },
    }
    assert rows[1]["function"] == "ComputeSPMV_ref"
    assert rows[1]["value"] == 19.070656
    assert rows[1]["percent"] == 28.07
    assert rows[2]["function"] == "ComputeDotProduct_ref"
    assert rows[2]["value"] == 1.391727
    assert rows[2]["percent"] == 2.05


# -- hotspots CSV: comma-delimited with hardware-event columns -----------------


def test_hotspots_comma_hw_csv_extra_columns() -> None:
    rows = parse_hotspots_csv((FIXTURES / "vtune_hotspots_comma_hw.csv").read_text())
    assert len(rows) == 2
    put = rows[0]
    assert put["function"] == "engine::TT::put"
    assert put["module"] == "frankycpp_v1.5.exe"
    assert put["value"] == 17.611828
    assert put["percent"] == 50.45
    assert put["extra"] == {
        "effective_time_sec": 17.611828,
        "spin_time_sec": 0.0,
        "overhead_time_sec": 0.0,
        "instructions_retired": 20662505000.0,
        "microarchitecture_usage_pct": 4.3,
        "cpi_rate": 4.495869,
    }
    probe = rows[1]
    assert probe["function"] == "engine::TT::probe"
    assert probe["value"] == 17.298849
    assert probe["extra"]["instructions_retired"] == 21240540000.0
    assert probe["extra"]["cpi_rate"] == 4.250564


def test_hotspots_csv_garbage_and_empty_are_safe() -> None:
    assert parse_hotspots_csv("") == []
    assert parse_hotspots_csv("vtune: Error: something\n") == []
    assert parse_hotspots_csv("Not,The,Header\n1,2,3\n") == []


# -- version -------------------------------------------------------------------


def test_parse_version_output() -> None:
    text = (
        "Intel(R) VTune(TM) Profiler 2025.1.0 (build 629235) Command Line Tool\n"
        "Copyright (C) 2009 Intel Corporation. All rights reserved.\n"
    )
    version = parse_version_output(text)
    assert version == "Intel(R) VTune(TM) Profiler 2025.1.0 (build 629235) Command Line Tool"
    assert parse_version_output("") == ""
