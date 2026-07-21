"""AMD uProf CLI (AMDuProfCLI) command construction.

Reference: uProf 4.2 user guide verified verbatim + 5.x docs
(docs/research/research-uprof-cli.md). Conventions that matter:
  * `collect -o <base>` creates a timestamped session dir
    `AMDuProf-<APP>-<CONFIG>_<Mon-DD-YYYY_hh-mm-ss>` UNDER the base dir; we
    give every collection a unique base dir so a glob fallback is unambiguous.
  * collect/profile announce outputs on stdout as
    `Generated data files path: <dir>` / `Generated report file: <file>`
    (exact strings confirmed in AMDResearch/intellikit source, MIT).
  * `report` emits CSV only; `-f/--format` belongs to `timechart`.
"""

from __future__ import annotations

from mcp.server.fastmcp.exceptions import ToolError

KNOWN_CONFIGS = [
    "tbp",
    "hotspots",
    "assess",
    "assess_ext",
    "data_access",
    "inst_access",
    "branch",
    "cpi",
    "threading",
    "ibs",
    "memory",
    "energy",
    "gpu",
    "overview",
]

CONFIG_CODES = {
    "tbp": "tbp",
    "hotspots": "hs",
    "assess": "as",
    "assess_ext": "asx",
    "data_access": "da",
    "inst_access": "ia",
    "branch": "br",
    "cpi": "cpi",
    "threading": "thr",
    "ibs": "ibs",
    "memory": "mem",
    "energy": "en",
    "gpu": "gpu",
    "overview": "ov",
}

TIMECHART_CATEGORIES = [
    "power",
    "frequency",
    "temperature",
    "voltage",
    "current",
    "dvfs",
    "energy",
]


def config_code(cfg: str) -> str:
    return CONFIG_CODES.get(cfg, "".join(c for c in cfg if c.isalnum())[:4] or "run")


def validate_config(cfg: str, *, allow_unknown: bool = False) -> str:
    if cfg in KNOWN_CONFIGS or allow_unknown:
        return cfg
    raise ToolError(
        f"Unknown collect config {cfg!r}. Known configs: {', '.join(KNOWN_CONFIGS)}. "
        "Pass allow_unknown=true to force (the live list is CPU/version-dependent; "
        "uprof_check reports what your installation supports). Note: on Intel CPUs "
        "only 'tbp' works — PMC/IBS configs need AMD hardware."
    )


def build_collect_argv(
    prefix: list[str],
    config: str,
    *,
    output_dir: str,
    command: list[str] | None = None,
    pid: int | None = None,
    duration_sec: float | None = None,
    call_graph: bool = False,
    working_dir: str | None = None,
    extra_events: list[str] | None = None,
) -> list[str]:
    if bool(command) == (pid is not None):
        raise ToolError("Pass exactly one of `command` (argv list) or `pid` (attach).")
    if pid is not None and duration_sec is None:
        raise ToolError("Attaching with `pid` requires `duration_sec`.")

    argv = [*prefix, "collect", "--config", config, "-o", output_dir, "--log-path", output_dir]
    if call_graph:
        argv.append("-g")
    if duration_sec is not None:
        argv += ["-d", str(int(duration_sec))]
    if working_dir:
        argv += ["-w", working_dir]
    for ev in extra_events or []:
        argv += ["-e", ev]
    if pid is not None:
        argv += ["-p", str(pid)]
    else:
        argv += list(command)  # type: ignore[arg-type]
    return argv


def build_report_argv(
    prefix: list[str],
    *,
    input_dir: str,
    report_output: str | None = None,
    cutoff: int | None = None,
    detail: bool = False,
    group_by: str | None = None,
    ignore_system_modules: bool = False,
    extra_args: list[str] | None = None,
) -> list[str]:
    argv = [*prefix, "report", "-i", input_dir]
    if report_output:
        argv += ["--report-output", report_output]
    if cutoff is not None:
        argv += ["--cutoff", str(cutoff)]
    if detail:
        argv.append("--detail")
        if group_by:
            argv += ["--group-by", group_by]
    elif group_by:
        raise ToolError("--group-by is only valid together with detail=true (uProf constraint).")
    if ignore_system_modules:
        argv.append("--ignore-system-module")
    for a in extra_args or []:
        if not a.startswith("-"):
            raise ToolError(f"extra_args entries must be AMDuProfCLI options (got {a!r}).")
        argv.append(a)
    return argv


def build_timechart_argv(
    prefix: list[str],
    *,
    events: list[str],
    output_dir: str,
    duration_sec: float,
    interval_ms: int = 100,
    command: list[str] | None = None,
) -> list[str]:
    if not events:
        raise ToolError(f"timechart needs at least one event category: {TIMECHART_CATEGORIES}")
    if interval_ms < 10:
        raise ToolError("uProf timechart minimum sampling interval is 10 ms.")
    argv = [*prefix, "timechart", "--event", ",".join(events), "-o", output_dir,
            "--interval", str(interval_ms), "--duration", str(int(duration_sec)),
            "--format", "csv"]
    if command:
        argv += list(command)
    return argv


def build_info_argv(prefix: list[str], *, what: str = "--system") -> list[str]:
    if what == "--system":
        return [*prefix, "info", "--system"]
    return [*prefix, "info", "--list", what]


def build_version_argv(prefix: list[str]) -> list[str]:
    return [*prefix, "--version"]
