"""Shared structured-output types for both MCP servers.

Every MCP tool returns one of these TypedDicts; the SDK derives output schemas
from them, so field names and types here are the wire contract. Keep values
JSON-native.

Two constraints verified against mcp 1.28.1 (do not "clean up"):
  * No `from __future__ import annotations` here — stringized annotations break
    NotRequired detection (__optional_keys__ ends up empty) and every field
    would be schema-required.
  * The SDK serializes omitted NotRequired fields as null and then fails its
    own output validation, so servers always populate them with a sentinel
    ('' / 0.0 / {}) instead of omitting.
"""

from typing import Literal, NotRequired, TypedDict

Mode = Literal["real", "mock", "unavailable"]


class CheckResult(TypedDict):
    """Environment probe result (`vtune_check` / `uprof_check`)."""

    server: str
    mode: Mode
    binary: str
    binary_found: bool
    version: NotRequired[str]
    platform: str
    results_dir: str
    available_analyses: list[str]
    notes: list[str]


class CollectResult(TypedDict):
    """Outcome of a profiling collection run."""

    result_id: str
    result_dir: str
    analysis: str
    mode: Mode
    target: str
    app_exit_code: NotRequired[int]
    elapsed_sec: float
    warnings: list[str]


class ResultInfo(TypedDict):
    """One entry in the stored-results registry."""

    result_id: str
    result_dir: str
    server: str
    analysis: str
    mode: Mode
    created_at: str
    target: str
    label: NotRequired[str]


class ResultList(TypedDict):
    results: list[ResultInfo]


class HotspotRow(TypedDict):
    """One function in a hotspots report, normalized across both profilers."""

    function: str
    module: str
    metric: str
    value: float
    percent: float
    extra: NotRequired[dict[str, float]]


class HotspotsReport(TypedDict):
    result_id: str
    metric: str
    total_value: float
    rows: list[HotspotRow]
    row_count_total: int
    truncated: bool
    notes: list[str]


class SummaryReport(TypedDict):
    result_id: str
    analysis: str
    elapsed_sec: NotRequired[float]
    cpu_time_sec: NotRequired[float]
    metrics: dict[str, float]
    top_hotspots: list[HotspotRow]
    platform_info: dict[str, str]
    notes: list[str]


class RawReport(TypedDict):
    """Escape-hatch report: capped text straight from the profiler CLI."""

    result_id: str
    command: list[str]
    text: str
    truncated: bool
    total_bytes: int


class CompareRow(TypedDict):
    function: str
    module: str
    baseline_value: float
    candidate_value: float
    delta: float
    delta_pct: float
    classification: Literal["regression", "improvement", "unchanged", "added", "removed"]


class RegressionVerdict(TypedDict):
    passed: bool
    threshold_pct: float
    worst_regression_pct: float
    reason: str


class CompareResult(TypedDict):
    baseline_id: str
    candidate_id: str
    metric: str
    total_baseline: float
    total_candidate: float
    total_delta_pct: float
    rows: list[CompareRow]
    verdict: RegressionVerdict
    notes: list[str]


class TimechartResult(TypedDict):
    """Summary of a uProf timechart (power/frequency/thermal) run."""

    result_id: str
    result_dir: str
    mode: Mode
    duration_sec: float
    interval_ms: int
    counters: dict[str, dict[str, float]]  # counter -> {min, max, mean, last}
    samples: int
    notes: list[str]


class SystemInfo(TypedDict):
    mode: Mode
    fields: dict[str, str]
    notes: list[str]
