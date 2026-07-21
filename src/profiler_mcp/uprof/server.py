"""FastMCP server "uprof" — AMD uProf (AMDuProfCLI) as MCP tools.

The `mcp` instance is a module attribute (tests import it). Config and the
result store are resolved per call, never cached at import, so environment
changes between tests take effect.

uProf specifics vs the vtune server: `collect -o <base>` creates a timestamped
session dir UNDER the base dir (we store the SESSION dir as result_dir), and
`report` writes CSV files instead of printing to stdout, so report tools read
the generated report.csv (cached in the session dir after first use).
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
    SystemInfo,
    TimechartResult,
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
    "No AMDuProfCLI binary found. Install AMD uProf or set UPROF_MCP_BIN to its path; "
    "or set PROFILER_MCP_MODE=mock to use the synthetic mock backend."
)
_REPORT_CUTOFF = 100  # match the top_n clamp so hotspots/compare never miss rows past 10
_HW_NOTE = (
    "On non-AMD CPUs only the 'tbp' (timer-based profiling) config works; "
    "PMC/IBS/energy configs need AMD hardware."
)
_VERSION_TIMEOUT_SEC = 30.0
_REPORT_TIMEOUT_SEC = 120.0
_DEFAULT_COLLECT_SEC = 300.0

_READ_ONLY = ToolAnnotations(readOnlyHint=True)

mcp = FastMCP(
    "uprof",
    instructions=(
        "AMD uProf profiler as MCP tools. Typical flow: uprof_check to probe the "
        "environment, uprof_collect to profile a command or PID (returns a result_id "
        "handle), uprof_report_summary / uprof_report_hotspots to inspect it, and "
        "uprof_compare for a baseline-vs-candidate regression verdict. uprof_timechart "
        "samples power/frequency/thermal counters; uprof_system_info describes the host. "
        "Results persist server-side; tools return capped structured summaries, never "
        "raw dumps. PMC/IBS/energy configs need AMD hardware ('tbp' works anywhere). "
        "Without a real AMDuProfCLI install the server runs in mock mode: deterministic "
        "synthetic data for exercising tool plumbing — never real hardware measurements."
    ),
)


def _session() -> tuple[ServerConfig, SessionStore]:
    cfg = resolve("uprof")
    return cfg, SessionStore(cfg.results_dir, "uprof")


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


def _find_session_dir(base_dir: Path, stdout: str) -> Path | None:
    """Session dir from `Generated data files path:` stdout, else newest glob match."""
    announced = parse.parse_collect_stdout(stdout).get("session_dir")
    if announced and Path(announced).is_dir():
        return Path(announced)
    candidates = [p for p in base_dir.glob("AMDuProf-*") if p.is_dir()]
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def _locate_report_csv(session: Path, stdout: str, preferred: Path) -> Path | None:
    """Report file: requested path, `Generated report file:` stdout, default, newest CSV."""
    if preferred.is_file():
        return preferred
    announced = parse.parse_collect_stdout(stdout).get("report_path")
    if announced and Path(announced).is_file():
        return Path(announced)
    default = session / "report.csv"
    if default.is_file():
        return default
    csvs = [p for p in session.glob("*.csv") if p.is_file()]
    return max(csvs, key=lambda p: p.stat().st_mtime) if csvs else None


def _run_report(
    cfg: ServerConfig,
    session: Path,
    out: Path,
    *,
    ignore_system_modules: bool = False,
    extra_args: list[str] | None = None,
) -> tuple[Path, list[str]]:
    argv = cli.build_report_argv(
        cfg.argv_prefix,
        input_dir=str(session),
        report_output=str(out),
        cutoff=_REPORT_CUTOFF,
        ignore_system_modules=ignore_system_modules,
        extra_args=extra_args,
    )
    res = require_success(run_command(argv, timeout_sec=_REPORT_TIMEOUT_SEC), "AMDuProfCLI report")
    path = _locate_report_csv(session, res.stdout, out)
    if path is None:
        raise ToolError(
            f"uProf report ran but no CSV file was found under {session}. "
            "The collection may be empty or corrupt; re-run uprof_collect."
        )
    return path, argv


def _report_csv(
    cfg: ServerConfig, entry: StoredResult, *, ignore_system_modules: bool = False
) -> tuple[Path, list[str]]:
    """Path of the parsed report CSV plus the argv that produces it (cached after first run)."""
    session = Path(entry.result_dir)
    out = session / ("report-nosys.csv" if ignore_system_modules else "report.csv")
    if out.is_file():
        argv = cli.build_report_argv(
            cfg.argv_prefix,
            input_dir=str(session),
            report_output=str(out),
            cutoff=_REPORT_CUTOFF,
            ignore_system_modules=ignore_system_modules,
        )
        return out, argv
    return _run_report(cfg, session, out, ignore_system_modules=ignore_system_modules)


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
    cfg: ServerConfig, entry: StoredResult, *, ignore_system_modules: bool = False
) -> list[HotspotRow]:
    path, _argv = _report_csv(cfg, entry, ignore_system_modules=ignore_system_modules)
    parsed = parse.parse_report_csv(path.read_text(errors="replace"))
    return sorted(_fill_rows(parsed["hottest_functions"]), key=lambda r: r["value"], reverse=True)


@mcp.tool(annotations=_READ_ONLY)
def uprof_check() -> CheckResult:
    """Probe the uProf environment: binary, version, platform, active mode, results dir.

    Call this before collecting. `mode` is "real" (actual AMDuProfCLI found), "mock"
    (deterministic synthetic backend — numbers are fabricated, useful only for testing
    tool plumbing), or "unavailable" (nothing runnable; notes explain how to fix).
    `available_analyses` lists the collect configs uprof_collect accepts; note that
    on non-AMD CPUs only 'tbp' actually works.
    """
    cfg, _store = _session()
    notes: list[str] = []
    result: CheckResult = {
        "server": "uprof",
        "mode": cfg.mode,
        "binary": cfg.binary,
        "binary_found": cfg.available,
        "version": "unknown",
        "platform": platform_summary(),
        "results_dir": str(cfg.results_dir),
        "available_analyses": list(cli.KNOWN_CONFIGS),
        "notes": notes,
    }
    if cfg.mode == "mock":
        notes.append(_MOCK_NOTE)
    if cfg.mode == "unavailable":
        notes.append(_UNAVAILABLE_NOTE)
        notes.append(_HW_NOTE)
        return result
    notes.append(_HW_NOTE)
    try:
        ver = run_command(cli.build_version_argv(cfg.argv_prefix), timeout_sec=_VERSION_TIMEOUT_SEC)
    except ToolError as e:
        notes.append(f"Version probe failed: {e}")
        return result
    if ver.ok:
        result["version"] = parse.parse_version_output(ver.stdout)
    else:
        notes.append(f"`AMDuProfCLI --version` exited {ver.exit_code}: {ver.stderr.strip()[:200]}")
    if cfg.mode == "real":
        _note_perf_paranoid(notes)
    return result


@mcp.tool()
def uprof_collect(
    config: str,
    command: list[str] | None = None,
    pid: int | None = None,
    duration_sec: float | None = None,
    call_graph: bool = False,
    working_dir: str | None = None,
    extra_events: list[str] | None = None,
    label: str = "",
    allow_unknown: bool = False,
    timeout_sec: float | None = None,
) -> CollectResult:
    """Run a uProf collection and store the result; returns a `result_id` handle.

    Pass exactly one target: `command` (argv list, launched under the profiler) or
    `pid` (attach — requires `duration_sec`, since attach has no natural end).
    `config` is a collect config such as "tbp" or "hotspots" (uprof_check lists
    them; only 'tbp' works on non-AMD CPUs; `allow_unknown=true` forces an unlisted
    one). `call_graph=true` adds call-stack sampling; `extra_events` are raw -e
    event specs; `label` is a free-form tag for telling results apart later.
    `timeout_sec` caps how long the collection may run before it is killed
    (default 300s, or `duration_sec` when larger); raise it for long workloads.
    `app_exit_code` is the profiled program's own exit — a non-zero value is
    surfaced as a warning, so a crashed target does not masquerade as a clean
    profile. In mock mode the target command really runs but every profile number
    is synthetic. Feed the returned result_id to the report/compare tools.
    """
    cfg, store = _session()
    _require_available(cfg)
    cli.validate_config(config, allow_unknown=allow_unknown)
    rid, base_dir = store.new_result_dir(cli.config_code(config))
    base_dir.mkdir(parents=True, exist_ok=True)  # uProf creates the session dir under it
    argv = cli.build_collect_argv(
        cfg.argv_prefix,
        config,
        output_dir=str(base_dir),
        command=command,
        pid=pid,
        duration_sec=duration_sec,
        call_graph=call_graph,
        working_dir=working_dir,
        extra_events=extra_events,
    )
    budget = timeout_sec if timeout_sec else (duration_sec or _DEFAULT_COLLECT_SEC)
    res = require_success(
        run_command(argv, timeout_sec=budget + cfg.timeout_grace),
        f"AMDuProfCLI collect {config}",
    )
    session = _find_session_dir(base_dir, res.stdout)
    if session is None:
        raise ToolError(
            "uProf collect reported success but no AMDuProf-* session dir was found "
            f"under {base_dir} and stdout announced none."
        )
    target = shlex.join(command) if command else f"pid:{pid}"
    store.register(rid, session, analysis=config, mode=cfg.mode, target=target, label=label)
    app_code = _app_exit_from_stderr(res.stderr)
    warnings = [ln.strip() for ln in res.stderr.splitlines() if "warning" in ln.lower()]
    if app_code is not None and app_code != 0:
        warnings.insert(
            0,
            f"Target application exited with non-zero code {app_code}; the profile may be "
            "incomplete or reflect a failed run — verify the run before trusting it.",
        )
    return {
        "result_id": rid,
        "result_dir": str(session),
        "analysis": config,
        "mode": cfg.mode,
        "target": target,
        # The profiled program's own exit (from the mock marker); falls back to the
        # profiler's exit in real mode, where uProf does not report the app's code.
        "app_exit_code": app_code if app_code is not None else res.exit_code,
        "elapsed_sec": round(res.elapsed_sec, 3),
        "warnings": warnings,
    }


@mcp.tool(annotations=_READ_ONLY)
def uprof_list_results() -> ResultList:
    """List stored uProf results: result_id, config, target, mode, creation time.

    Use to rediscover result_ids from earlier collections. Entries stamped
    mode "mock" contain synthetic numbers.
    """
    _cfg, store = _session()
    results = store.list()
    for r in results:
        r.setdefault("label", "")
    return {"results": results}


@mcp.tool(annotations=_READ_ONLY)
def uprof_report_summary(result_id: str) -> SummaryReport:
    """Parsed run overview of a stored result: duration, top hotspots, host details.

    Generates the CSV report on first use (cached in the session dir afterwards).
    The fastest way to understand a collection before drilling into hotspots.
    `result_id` comes from uprof_collect or uprof_list_results.
    """
    cfg, store = _session()
    entry = store.get(result_id)
    _require_available(cfg)
    _require_mode_match(cfg, entry)
    path, _argv = _report_csv(cfg, entry)
    parsed = parse.parse_report_csv(path.read_text(errors="replace"))
    duration = float(parsed["duration_sec"] or 0.0)
    # uProf has no aggregate CPU-time line, but the HOTTEST PROCESSES section sums
    # the per-process CPU_TIME; use that (fallback to threads) as the total.
    cpu_time = sum(p.get("value", 0.0) for p in parsed["hottest_processes"])
    if not cpu_time:
        cpu_time = sum(t.get("value", 0.0) for t in parsed["hottest_threads"])
    metrics: dict[str, float] = {"duration_sec": duration} if duration else {}
    if cpu_time:
        metrics["cpu_time_sec"] = round(cpu_time, 6)
    notes = [*parsed["notes"], *_mode_notes(entry)]
    if parsed["monitored_events"]:
        events = ", ".join(map(str, parsed["monitored_events"]))
        notes.append(f"Monitored events: {events}")
    if not parsed["hottest_functions"]:
        notes.append(_EMPTY_NOTE)
    return {
        "result_id": result_id,
        "analysis": entry.analysis,
        "elapsed_sec": duration,
        "cpu_time_sec": round(cpu_time, 6),
        "metrics": metrics,
        "top_hotspots": _fill_rows(parsed["hottest_functions"][:5]),
        "platform_info": {str(k): str(v) for k, v in parsed["execution"].items()},
        "notes": notes,
    }


@mcp.tool(annotations=_READ_ONLY)
def uprof_report_hotspots(
    result_id: str,
    top_n: int = 10,
    ignore_system_modules: bool = False,
) -> HotspotsReport:
    """Top-N hottest functions of a stored result, sorted by sample share descending.

    `top_n` is clamped to 100; `row_count_total` and `truncated` say whether more
    rows exist. `ignore_system_modules=true` re-runs the report excluding kernel
    and system libraries so application code stands out. Start with the defaults.
    """
    cfg, store = _session()
    entry = store.get(result_id)
    _require_available(cfg)
    _require_mode_match(cfg, entry)
    top = clamp_top_n(top_n)
    rows = _hotspot_rows(cfg, entry, ignore_system_modules=ignore_system_modules)
    notes = _mode_notes(entry)
    if not rows:
        notes.append(_EMPTY_NOTE)
    return {
        "result_id": result_id,
        "metric": rows[0]["metric"] if rows else "samples",
        "total_value": round(sum(r["value"] for r in rows), 6),
        "rows": rows[:top],
        "row_count_total": len(rows),
        "truncated": len(rows) > top,
        "notes": notes,
    }


@mcp.tool(annotations=_READ_ONLY)
def uprof_report_raw(
    result_id: str,
    extra_args: list[str] | None = None,
) -> RawReport:
    """Escape hatch: raw uProf CSV report text for a stored result, byte-capped.

    uProf's report subcommand writes CSV files rather than printing to stdout, so
    this returns the contents of the generated report.csv (cached after first
    use). With `extra_args` (raw AMDuProfCLI report options, each starting with
    "-") the report is regenerated into report-raw.csv using those options.
    `command` is the CLI invocation that produces the file. Long output is
    head+tail truncated; read files under result_dir for the full data.
    """
    cfg, store = _session()
    entry = store.get(result_id)
    _require_available(cfg)
    _require_mode_match(cfg, entry)
    if extra_args:
        session = Path(entry.result_dir)
        path, argv = _run_report(cfg, session, session / "report-raw.csv", extra_args=extra_args)
    else:
        path, argv = _report_csv(cfg, entry)
    raw = path.read_text(errors="replace")
    text, truncated = cap_text(raw)
    return {
        "result_id": result_id,
        "command": argv,
        "text": text,
        "truncated": truncated,
        "total_bytes": len(raw.encode("utf-8", errors="replace")),
    }


@mcp.tool()
def uprof_compare(
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
        metric = "samples"
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


@mcp.tool()
def uprof_timechart(
    events: list[str],
    duration_sec: float,
    interval_ms: int = 100,
    command: list[str] | None = None,
) -> TimechartResult:
    """Sample system power/frequency/thermal counters over time and summarize them.

    `events` are timechart categories (power, frequency, temperature, voltage,
    current, dvfs, energy). Samples every `interval_ms` (minimum 10) for
    `duration_sec`, optionally while running `command`. Returns per-counter
    min/max/mean/last summaries, not the full series — the CSV stays in
    result_dir. Real data needs AMD hardware; in mock mode values are synthetic.
    """
    cfg, store = _session()
    _require_available(cfg)
    rid, base_dir = store.new_result_dir("tc")
    base_dir.mkdir(parents=True, exist_ok=True)
    argv = cli.build_timechart_argv(
        cfg.argv_prefix,
        events=events,
        output_dir=str(base_dir),
        duration_sec=duration_sec,
        interval_ms=interval_ms,
        command=command,
    )
    res = require_success(
        run_command(argv, timeout_sec=float(duration_sec) + cfg.timeout_grace),
        "AMDuProfCLI timechart",
    )
    csv_path = _find_timechart_csv(base_dir, res.stdout)
    if csv_path is None:
        raise ToolError(f"uProf timechart ran but produced no CSV file under {base_dir}.")
    parsed = parse.parse_timechart_csv(csv_path.read_text(errors="replace"))
    result_dir = csv_path.parent
    target = shlex.join(command) if command else "system-wide"
    store.register(rid, result_dir, analysis="timechart", mode=cfg.mode, target=target)
    notes = [f"{k}: {v}" for k, v in parsed["details"].items()]
    if cfg.mode == "mock":
        notes.append(_MOCK_NOTE)
    return {
        "result_id": rid,
        "result_dir": str(result_dir),
        "mode": cfg.mode,
        "duration_sec": float(duration_sec),
        "interval_ms": interval_ms,
        "counters": parsed["counters"],
        "samples": parsed["samples"],
        "notes": notes,
    }


def _find_timechart_csv(base_dir: Path, stdout: str) -> Path | None:
    """CSV path from `Live Profile Output file : ` stdout, else newest CSV in the tree."""
    for ln in stdout.splitlines():
        if "Live Profile Output file" in ln:
            candidate = Path(ln.partition(":")[2].strip())
            if candidate.is_file():
                return candidate
    csvs = [p for p in base_dir.rglob("*.csv") if p.is_file()]
    return max(csvs, key=lambda p: p.stat().st_mtime) if csvs else None


@mcp.tool(annotations=_READ_ONLY)
def uprof_system_info() -> SystemInfo:
    """Parsed `AMDuProfCLI info --system`: CPU model/family, core counts, OS details.

    Use to decide which collect configs the hardware supports before profiling.
    In mock mode the fields are synthetic.
    """
    cfg, _store = _session()
    _require_available(cfg)
    res = require_success(
        run_command(cli.build_info_argv(cfg.argv_prefix), timeout_sec=_VERSION_TIMEOUT_SEC),
        "AMDuProfCLI info --system",
    )
    fields: dict[str, str] = {}
    for ln in res.stdout.splitlines():
        key, sep, val = ln.partition(":")
        if sep and key.strip() and val.strip():
            fields[key.strip()] = val.strip()
    notes = [_MOCK_NOTE] if cfg.mode == "mock" else []
    return {"mode": cfg.mode, "fields": fields, "notes": notes}


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="uprof-mcp", description="MCP server for the AMD uProf CLI (AMDuProfCLI)."
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
