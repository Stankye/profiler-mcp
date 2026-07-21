"""FastMCP server "vtune" — Intel VTune Profiler as MCP tools.

The `mcp` instance is a module attribute (tests import it). Config and the
result store are resolved per call, never cached at import, so environment
changes between tests take effect.
"""

from __future__ import annotations

import argparse
import shlex
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from ..core.compare import compare_hotspots
from ..core.config import ServerConfig, platform_summary, resolve
from ..core.models import (
    CheckResult,
    CollectResult,
    CompareResult,
    HotspotRow,
    HotspotsReport,
    RawReport,
    ResultList,
    SummaryReport,
)
from ..core.runner import require_success, run_command
from ..core.store import SessionStore, StoredResult
from ..core.textcap import cap_text, clamp_top_n
from . import cli, parse

_MOCK_NOTE = "Mock mode: synthetic data — do not treat numbers as real hardware measurements."
_EMPTY_NOTE = (
    "Report is empty — the collection produced no function samples. The workload may have "
    "run too briefly, exited early, or collected nothing; check the collect warnings."
)
_UNAVAILABLE_NOTE = (
    "No vtune binary found. Install Intel VTune (oneAPI) or set VTUNE_MCP_BIN to its path; "
    "or set PROFILER_MCP_MODE=mock to use the synthetic mock backend."
)
_VERSION_TIMEOUT_SEC = 30.0
_REPORT_TIMEOUT_SEC = 120.0
_DEFAULT_COLLECT_SEC = 300.0

_READ_ONLY = ToolAnnotations(readOnlyHint=True)

mcp = FastMCP(
    "vtune",
    instructions=(
        "Intel VTune Profiler as MCP tools. Typical flow: vtune_check to probe the "
        "environment, vtune_collect to profile a command or PID (returns a result_id "
        "handle), vtune_report_summary / vtune_report_hotspots to inspect it, and "
        "vtune_compare for a baseline-vs-candidate regression verdict. Results persist "
        "server-side; tools return capped structured summaries, never raw dumps. "
        "Without a real vtune install the server runs in mock mode: deterministic "
        "synthetic data for exercising tool plumbing — never real hardware measurements."
    ),
)


def _session() -> tuple[ServerConfig, SessionStore]:
    cfg = resolve("vtune")
    return cfg, SessionStore(cfg.results_dir, "vtune")


def _require_available(cfg: ServerConfig) -> None:
    if not cfg.available:
        raise ToolError(_UNAVAILABLE_NOTE)


def _mode_notes(*entries: StoredResult) -> list[str]:
    """Notes derived from the modes results were COLLECTED in (not the current config)."""
    notes: list[str] = []
    modes = [e.mode for e in entries]
    if len(set(modes)) > 1:
        notes.append(
            "Results were collected in different modes ("
            + " vs ".join(modes)
            + ") — their numbers are not comparable."
        )
    if "mock" in modes:
        notes.append(_MOCK_NOTE)
    return notes


def _note_perf_paranoid(notes: list[str]) -> None:
    try:
        level = int(Path("/proc/sys/kernel/perf_event_paranoid").read_text().strip())
    except (OSError, ValueError):
        return
    if level > 1:
        notes.append(
            f"perf_event_paranoid={level}: driverless hardware sampling may be restricted "
            "(needs <=1; sudo sysctl kernel.perf_event_paranoid=1)."
        )


def _require_mode_match(cfg: ServerConfig, *entries: StoredResult) -> None:
    """A stored result can only be re-read by the backend that produced it."""
    for e in entries:
        if e.mode != cfg.mode:
            raise ToolError(
                f"Result {e.result_id} was collected in {e.mode!r} mode, but the server "
                f"is now in {cfg.mode!r} mode — the {cfg.mode} backend cannot read a "
                f"{e.mode} result. Re-collect it, or set PROFILER_MCP_MODE={e.mode}."
            )


_APP_EXIT_MARKER = "profiler-mcp-mock: app-exit-code="


def _app_exit_from_stderr(stderr: str) -> int | None:
    """Target's real exit code from the mock marker; None in real mode (no marker)."""
    for ln in stderr.splitlines():
        if ln.startswith(_APP_EXIT_MARKER):
            val = ln[len(_APP_EXIT_MARKER) :].strip()
            return int(val) if val else None
    return None


# mcp 1.28 dumps omitted NotRequired fields as null and then rejects them against
# its own output schema, so every NotRequired field is always populated here.
def _fill_rows(rows: list[HotspotRow]) -> list[HotspotRow]:
    for r in rows:
        r.setdefault("extra", {})
    return rows


def _hotspot_rows(
    cfg: ServerConfig,
    entry: StoredResult,
    *,
    group_by: str | None = None,
    filters: list[str] | None = None,
) -> list[HotspotRow]:
    argv = cli.build_report_argv(
        cfg.argv_prefix,
        "hotspots",
        result_dir=entry.result_dir,
        csv=True,
        group_by=group_by,
        filters=filters,
    )
    res = require_success(
        run_command(argv, timeout_sec=_REPORT_TIMEOUT_SEC), "vtune report hotspots"
    )
    rows = _fill_rows(parse.parse_hotspots_csv(res.stdout))
    return sorted(rows, key=lambda r: r["value"], reverse=True)


@mcp.tool(annotations=_READ_ONLY)
def vtune_check() -> CheckResult:
    """Probe the VTune environment: binary, version, platform, active mode, results dir.

    Call this before collecting. `mode` is "real" (actual Intel VTune found), "mock"
    (deterministic synthetic backend — numbers are fabricated, useful only for testing
    tool plumbing), or "unavailable" (nothing runnable; notes explain how to fix).
    `available_analyses` lists the analysis types vtune_collect accepts.
    """
    cfg, _store = _session()
    notes: list[str] = []
    result: CheckResult = {
        "server": "vtune",
        "mode": cfg.mode,
        "binary": cfg.binary,
        "binary_found": cfg.available,
        "version": "unknown",
        "platform": platform_summary(),
        "results_dir": str(cfg.results_dir),
        "available_analyses": list(cli.KNOWN_ANALYSES),
        "notes": notes,
    }
    if cfg.mode == "mock":
        notes.append(_MOCK_NOTE)
    if cfg.mode == "unavailable":
        notes.append(_UNAVAILABLE_NOTE)
        return result
    try:
        ver = run_command(cli.build_version_argv(cfg.argv_prefix), timeout_sec=_VERSION_TIMEOUT_SEC)
    except ToolError as e:
        notes.append(f"Version probe failed: {e}")
        return result
    if ver.ok:
        result["version"] = parse.parse_version_output(ver.stdout)
    else:
        notes.append(f"`vtune -version` exited {ver.exit_code}: {ver.stderr.strip()[:200]}")
    if cfg.mode == "real":
        _note_perf_paranoid(notes)
    return result


@mcp.tool()
def vtune_collect(
    analysis: str,
    command: list[str] | None = None,
    pid: int | None = None,
    duration_sec: float | None = None,
    knobs: dict[str, str] | None = None,
    working_dir: str | None = None,
    data_limit_mb: int | None = None,
    label: str = "",
    allow_unknown: bool = False,
    timeout_sec: float | None = None,
) -> CollectResult:
    """Run a VTune collection and store the result; returns a `result_id` handle.

    Pass exactly one target: `command` (argv list, launched under the profiler) or
    `pid` (attach — requires `duration_sec`, since attach has no natural end).
    `analysis` is a VTune analysis type such as "hotspots" (vtune_check lists them;
    `allow_unknown=true` forces an unlisted one). `knobs` are analysis knobs
    (name -> value); `label` is a free-form tag for telling results apart later.
    `timeout_sec` caps how long the collection may run before it is killed
    (default 300s, or `duration_sec` when larger); raise it for long workloads.
    `app_exit_code` in the result is the profiled program's own exit — a non-zero
    value is surfaced as a warning, so a crashed target does not masquerade as a
    clean profile. In mock mode the target command really runs but every profile
    number is synthetic. Feed the returned result_id to the report/compare tools.
    """
    cfg, store = _session()
    _require_available(cfg)
    cli.validate_analysis(analysis, allow_unknown=allow_unknown)
    rid, rdir = store.new_result_dir(cli.analysis_code(analysis))
    argv = cli.build_collect_argv(
        cfg.argv_prefix,
        analysis,
        result_dir=str(rdir),
        command=command,
        pid=pid,
        duration_sec=duration_sec,
        knobs=knobs,
        working_dir=working_dir,
        data_limit_mb=data_limit_mb,
    )
    budget = timeout_sec if timeout_sec else (duration_sec or _DEFAULT_COLLECT_SEC)
    res = require_success(
        run_command(argv, timeout_sec=budget + cfg.timeout_grace), f"vtune collect {analysis}"
    )
    target = shlex.join(command) if command else f"pid:{pid}"
    store.register(rid, rdir, analysis=analysis, mode=cfg.mode, target=target, label=label)
    app_code = _app_exit_from_stderr(res.stderr)
    warnings = [ln.strip() for ln in res.stderr.splitlines() if "vtune: Warning:" in ln]
    if app_code is not None and app_code != 0:
        warnings.insert(
            0,
            f"Target application exited with non-zero code {app_code}; the profile may be "
            "incomplete or reflect a failed run — verify the run before trusting it.",
        )
    return {
        "result_id": rid,
        "result_dir": str(rdir),
        "analysis": analysis,
        "mode": cfg.mode,
        "target": target,
        # The profiled program's own exit (from the mock marker); falls back to the
        # profiler's exit in real mode, where the app's code is not separately reported.
        "app_exit_code": app_code if app_code is not None else res.exit_code,
        "elapsed_sec": round(res.elapsed_sec, 3),
        "warnings": warnings,
    }


@mcp.tool(annotations=_READ_ONLY)
def vtune_list_results() -> ResultList:
    """List stored VTune results: result_id, analysis, target, mode, creation time.

    Use to rediscover result_ids from earlier collections. Entries stamped
    mode "mock" contain synthetic numbers.
    """
    _cfg, store = _session()
    results = store.list()
    for r in results:
        r.setdefault("label", "")
    return {"results": results}


@mcp.tool(annotations=_READ_ONLY)
def vtune_report_summary(result_id: str) -> SummaryReport:
    """Parsed run overview of a stored result: elapsed/CPU time, key metrics, top hotspots.

    The fastest way to understand a collection before drilling into hotspots.
    `result_id` comes from vtune_collect or vtune_list_results.
    """
    cfg, store = _session()
    entry = store.get(result_id)
    _require_available(cfg)
    _require_mode_match(cfg, entry)
    argv = cli.build_report_argv(cfg.argv_prefix, "summary", result_dir=entry.result_dir, csv=False)
    res = require_success(
        run_command(argv, timeout_sec=_REPORT_TIMEOUT_SEC), "vtune report summary"
    )
    parsed = parse.parse_summary_text(res.stdout)
    elapsed = float(parsed["elapsed_sec"] or 0.0)
    cpu = float(parsed["cpu_time_sec"] or 0.0)
    notes = [*parsed["notes"], *_mode_notes(entry)]
    if not parsed["top_hotspots"] and elapsed == 0.0 and cpu == 0.0:
        notes.append(_EMPTY_NOTE)
    return {
        "result_id": result_id,
        "analysis": entry.analysis,
        "elapsed_sec": elapsed,
        "cpu_time_sec": cpu,
        "metrics": parsed["metrics"],
        "top_hotspots": _fill_rows(parsed["top_hotspots"]),
        "platform_info": parsed["platform_info"],
        "notes": notes,
    }


@mcp.tool(annotations=_READ_ONLY)
def vtune_report_hotspots(
    result_id: str,
    top_n: int = 10,
    group_by: str | None = None,
    filters: list[str] | None = None,
) -> HotspotsReport:
    """Top-N hottest functions of a stored result, sorted by CPU time descending.

    `top_n` is clamped to 100; `row_count_total` and `truncated` say whether more
    rows exist. `group_by` maps to vtune -group-by (e.g. "module"); each `filters`
    entry maps to -filter (e.g. "module=a.out"). Start with the defaults.
    """
    cfg, store = _session()
    entry = store.get(result_id)
    _require_available(cfg)
    _require_mode_match(cfg, entry)
    top = clamp_top_n(top_n)
    rows = _hotspot_rows(cfg, entry, group_by=group_by, filters=filters)
    notes = _mode_notes(entry)
    if not rows:
        notes.append(_EMPTY_NOTE)
    return {
        "result_id": result_id,
        "metric": rows[0]["metric"] if rows else "CPU Time",
        "total_value": round(sum(r["value"] for r in rows), 6),
        "rows": rows[:top],
        "row_count_total": len(rows),
        "truncated": len(rows) > top,
        "notes": notes,
    }


@mcp.tool(annotations=_READ_ONLY)
def vtune_report_raw(
    result_id: str,
    report_type: str,
    extra_args: list[str] | None = None,
    allow_unknown: bool = False,
) -> RawReport:
    """Escape hatch: run any vtune report type and return its text output, byte-capped.

    Use when the structured summary/hotspots tools do not expose what you need
    (e.g. "callstacks", "top-down", "hw-events"). `extra_args` are raw vtune report
    options, each starting with "-". Long output is head+tail truncated; read files
    under the stored result_dir for the full data.
    """
    cfg, store = _session()
    entry = store.get(result_id)
    _require_available(cfg)
    _require_mode_match(cfg, entry)
    if report_type not in cli.KNOWN_REPORT_TYPES and not allow_unknown:
        raise ToolError(
            f"Unknown report type {report_type!r}. Known: {', '.join(cli.KNOWN_REPORT_TYPES)}. "
            "Pass allow_unknown=true to force (the live list is version-dependent)."
        )
    argv = cli.build_report_argv(
        cfg.argv_prefix,
        report_type,
        result_dir=entry.result_dir,
        csv=False,
        extra_args=extra_args,
    )
    res = require_success(
        run_command(argv, timeout_sec=_REPORT_TIMEOUT_SEC), f"vtune report {report_type}"
    )
    text, truncated = cap_text(res.stdout)
    return {
        "result_id": result_id,
        "command": argv,
        "text": text,
        "truncated": truncated,
        "total_bytes": len(res.stdout.encode("utf-8", errors="replace")),
    }


@mcp.tool()
def vtune_compare(
    baseline_id: str,
    candidate_id: str,
    threshold_pct: float = 5.0,
    noise_floor_pct: float = 1.0,
    fail_on_regression: bool = False,
) -> CompareResult:
    """Compare two stored results function-by-function and issue a pass/fail verdict.

    The core of an optimize loop: collect a baseline, change code, collect a
    candidate, compare. The verdict fails when the total or any significant
    function regresses more than `threshold_pct`; functions below
    `noise_floor_pct` of both runs never affect the verdict. With
    `fail_on_regression=true` a failing verdict raises a tool error carrying the
    reason — use that to gate automated loops.
    """
    cfg, store = _session()
    base = store.get(baseline_id)
    cand = store.get(candidate_id)
    _require_available(cfg)
    _require_mode_match(cfg, base, cand)
    base_rows = _hotspot_rows(cfg, base)[:100]
    cand_rows = _hotspot_rows(cfg, cand)[:100]
    rows, verdict, total_base, total_cand, total_delta = compare_hotspots(
        base_rows, cand_rows, threshold_pct=threshold_pct, noise_floor_pct=noise_floor_pct
    )
    if base_rows:
        metric = base_rows[0]["metric"]
    elif cand_rows:
        metric = cand_rows[0]["metric"]
    else:
        metric = "CPU Time"
    result: CompareResult = {
        "baseline_id": baseline_id,
        "candidate_id": candidate_id,
        "metric": metric,
        "total_baseline": total_base,
        "total_candidate": total_cand,
        "total_delta_pct": total_delta,
        "rows": rows,
        "verdict": verdict,
        "notes": _mode_notes(base, cand),
    }
    if fail_on_regression and not verdict["passed"]:
        raise ToolError(f"Regression gate failed: {verdict['reason']}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="vtune-mcp", description="MCP server for the Intel VTune Profiler CLI."
    )
    parser.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.transport == "streamable-http":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
