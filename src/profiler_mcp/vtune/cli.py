"""Intel VTune CLI command construction.

Reference: VTune 2024.1+ CLI (`vtune`, formerly amplxe-cl). Conventions that
matter for automation (docs/research/research-vtune-cli.md):
  * `-result-dir` is ALWAYS passed explicitly — without it VTune silently picks
    the highest-numbered result in the CWD.
  * `-knob` options must precede the target; the target follows `--`.
  * collect and report cannot be combined in one invocation.
"""

from __future__ import annotations

from mcp.server.fastmcp.exceptions import ToolError

# 2024.1 documented analysis types; passed-through values are validated against
# this list unless allow_unknown, because the live set is version-dependent.
KNOWN_ANALYSES = [
    "performance-snapshot",
    "hotspots",
    "anomaly-detection",
    "threading",
    "hpc-performance",
    "memory-consumption",
    "uarch-exploration",
    "memory-access",
    "gpu-hotspots",
    "gpu-offload",
    "graphics-rendering",
    "npu",
    "fpga-interaction",
    "io",
    "system-overview",
]

KNOWN_REPORT_TYPES = [
    "summary",
    "hotspots",
    "callstacks",
    "top-down",
    "hw-events",
    "affinity",
    "exec-query",
    "gprof-cc",
    "platform-power-analysis",
    "timeline",
    "vectspots",
]

# Result-id prefixes per analysis, mirroring VTune's own r000hs naming spirit.
ANALYSIS_CODES = {
    "hotspots": "hs",
    "threading": "tr",
    "uarch-exploration": "ue",
    "memory-access": "ma",
    "memory-consumption": "mc",
    "hpc-performance": "hpc",
    "performance-snapshot": "ps",
    "io": "io",
    "system-overview": "so",
}


def analysis_code(analysis: str) -> str:
    return ANALYSIS_CODES.get(analysis, "".join(c for c in analysis if c.isalnum())[:4] or "run")


def validate_analysis(analysis: str, *, allow_unknown: bool = False) -> str:
    if analysis in KNOWN_ANALYSES or allow_unknown:
        return analysis
    raise ToolError(
        f"Unknown analysis type {analysis!r}. Known types: {', '.join(KNOWN_ANALYSES)}. "
        "Pass allow_unknown=true to force (the live list is version-dependent; "
        "vtune_check reports what your installation supports)."
    )


def build_collect_argv(
    prefix: list[str],
    analysis: str,
    *,
    result_dir: str,
    command: list[str] | None = None,
    pid: int | None = None,
    duration_sec: float | None = None,
    knobs: dict[str, str] | None = None,
    working_dir: str | None = None,
    data_limit_mb: int | None = None,
) -> list[str]:
    if bool(command) == (pid is not None):
        raise ToolError("Pass exactly one of `command` (argv list) or `pid` (attach).")
    if pid is not None and duration_sec is None:
        raise ToolError(
            "Attaching with `pid` requires `duration_sec` (collection has no natural end)."
        )

    argv = [*prefix, "-collect", analysis, "-result-dir", result_dir, "-quiet"]
    for name, value in (knobs or {}).items():
        argv += ["-knob", f"{name}={value}"]
    if duration_sec is not None:
        argv += ["-duration", str(int(duration_sec))]
    if working_dir:
        argv += ["-app-working-dir", working_dir]
    if data_limit_mb is not None:
        argv += ["-data-limit", str(data_limit_mb)]
    if pid is not None:
        argv += ["-target-pid", str(pid)]
    else:
        argv += ["--", *command]  # type: ignore[list-item]
    return argv


def build_report_argv(
    prefix: list[str],
    report_type: str,
    *,
    result_dir: str,
    csv: bool = True,
    report_output: str | None = None,
    group_by: str | None = None,
    filters: list[str] | None = None,
    limit: int | None = None,
    extra_args: list[str] | None = None,
) -> list[str]:
    argv = [*prefix, "-report", report_type, "-result-dir", result_dir, "-quiet"]
    if csv:
        argv += ["-format", "csv", "-csv-delimiter", "comma"]
    if report_output:
        argv += ["-report-output", report_output]
    if group_by:
        argv += ["-group-by", group_by]
    for f in filters or []:
        argv += ["-filter", f]
    if limit is not None:
        argv += ["-limit", str(limit)]
    for a in extra_args or []:
        if not a.startswith("-"):
            raise ToolError(f"extra_args entries must be vtune options (got {a!r}).")
        argv.append(a)
    return argv


def build_version_argv(prefix: list[str]) -> list[str]:
    return [*prefix, "-version"]
