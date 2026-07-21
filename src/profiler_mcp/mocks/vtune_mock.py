#!/usr/bin/env python3
"""Mock of the Intel VTune Profiler CLI (`vtune`).

Byte-realistic per docs/research/captures-vtune.md: everything `vtune:`-prefixed
(status, progress, warnings, errors) goes to stderr; report bodies and the
target application's own output go to stdout. Flag parsing is STRICT — any
option the servers never emit is `Unknown option` + exit 1, so regressions in
server command construction fail loudly.

Stdlib only; invoked as `python vtune_mock.py ...` (see core/config.py).
Deterministic: sample attribution comes from `<target>.mockprofile.json` next
to the target binary (or a generic fallback), scaled by measured wall time at
a nominal 10 ms sampling interval. No randomness anywhere.

Env contract:
  MOCK_FAIL       collect-perm | collect-hang | report-empty | bad-exit
  MOCK_FIXED_TIME unix seconds used for every emitted timestamp
"""

from __future__ import annotations

import csv
import io
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

KNOWN_ANALYSES = {
    "performance-snapshot", "hotspots", "anomaly-detection", "threading",
    "hpc-performance", "memory-consumption", "uarch-exploration", "memory-access",
    "gpu-hotspots", "gpu-offload", "graphics-rendering", "npu", "fpga-interaction",
    "io", "system-overview",
}

ANALYSIS_CODES = {
    "hotspots": "hs", "threading": "tr", "uarch-exploration": "ue",
    "memory-access": "ma", "memory-consumption": "mc", "hpc-performance": "hpc",
    "performance-snapshot": "ps", "io": "io", "system-overview": "so",
}

VERSION_TEXT = (
    "Intel(R) VTune(TM) Profiler 2025.1.0 (build 629235) Command Line Tool\n"
    "Copyright (C) 2009 Intel Corporation. All rights reserved.\n"
)

HELP_TEXT = (
    "Usage: vtune <-action> [-action-option] [-global-option] "
    "[[--] <target> [target options]]\n"
    "\nAvailable actions (mock):\n"
    "    collect    Collect performance data (-collect <analysis> -result-dir <dir>).\n"
    "    report     Generate a report (-report summary|hotspots -result-dir <dir>).\n"
    "    version    Display version information (-version).\n"
)

# Verbatim capture: hw-sampling collect refusal (perf_event_paranoid / drivers).
PERM_FAIL_LINES = [
    "vtune: Error: This analysis requires one of these actions: a) Install Intel Sampling "
    "Drivers. b) Configure driverless collection with Perf system-wide profiling. To enable "
    "Perf system-wide profiling, set /proc/sys/kernel/perf_event_paranoid to 1 or set up "
    "Perf tool capabilities.",
    "vtune: Warning: Access to /proc/kallsyms file is limited. Consider changing "
    "/proc/sys/kernel/kptr_restrict to 0 to enable resolution of OS kernel and kernel "
    "module symbols.",
]

# Finalization milestone sequence (subset of the captured transcript).
PROGRESS = [
    (0, ""), (0, "Finalizing results"), (0, "Finalizing the result"),
    (0, "Clearing the database"), (7, "Clearing the database"),
    (7, "Loading raw data to the database"), (12, "Loading raw data to the database"),
    (12, "Updating precomputed scalar metrics"), (14, "Updating precomputed scalar metrics"),
    (14, "Processing profile metrics and debug information"),
    (19, "Processing profile metrics and debug information"),
    (19, "Setting data model parameters"), (19, "Resolving module symbols"),
    (22, "Resolving bottom user stack information"), (23, "Resolving thread name information"),
    (24, "Resolving call target names for dynamic code"),
    (25, "Resolving interrupt name information"),
    (26, "Processing profile metrics and debug information"),
    (30, "Setting data model parameters"), (30, "Precomputing frequently used data"),
    (36, "Updating precomputed scalar metrics"), (37, "Discarding redundant overtime data"),
    (39, "Saving the result"), (50, "Saving the result"), (50, "Generating a report"),
    (50, "Setting data model parameters"), (75, "Setting data model parameters"),
    (75, "Generating a report"),
]

HINT_BLOCK = [
    "If you want to skip descriptions of detected performance issues in the report,",
    "enter: vtune -report summary -report-knob show-issues=false -r <my_result_dir>.",
    "Alternatively, you may view the report in the csv format: vtune -report",
    "<report_name> -format=csv.",
]

CSV_HEADER = [
    "Function", "CPU Time", "CPU Time:Effective Time", "CPU Time:Spin Time",
    "CPU Time:Overhead Time", "Module", "Function (Full)", "Source File", "Start Address",
]

VALUE_FLAGS = {
    "-collect", "-report", "-result-dir", "-r", "-knob", "-duration", "-app-working-dir",
    "-data-limit", "-target-pid", "-format", "-csv-delimiter", "-report-output",
    "-group-by", "-filter", "-limit", "-report-knob",
}
BOOL_FLAGS = {"-quiet", "-q", "-version", "-help"}


def err(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


def die(line: str) -> int:
    err(line)
    return 1


def fixed_time() -> float | None:
    raw = os.environ.get("MOCK_FIXED_TIME")
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def fmt_utc(unix: float) -> str:
    return datetime.fromtimestamp(unix, tz=UTC).strftime("%H:%M:%S %d/%m/%Y UTC")


def parse_args(argv: list[str]) -> dict | int:
    o: dict = {
        "collect": None, "report": None, "result_dir": None, "knobs": [], "duration": None,
        "working_dir": None, "data_limit": None, "pid": None, "format": None,
        "csv_delimiter": None, "report_output": None, "group_by": None, "filters": [],
        "limit": None, "report_knobs": [], "quiet": False, "version": False, "help": False,
        "command": None,
    }
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--":
            o["command"] = argv[i + 1:]
            if not o["command"]:
                return die("vtune: Error: The application to launch is not specified.")
            break
        flag, eq, inline = arg.partition("=")
        if flag in BOOL_FLAGS:
            if eq:
                return die(f"vtune: Error: Unknown option `{arg}'.")
            if flag in ("-quiet", "-q"):
                o["quiet"] = True
            elif flag == "-version":
                o["version"] = True
            else:
                o["help"] = True
            i += 1
            continue
        if flag in VALUE_FLAGS:
            if eq:
                value = inline
            else:
                i += 1
                if i >= len(argv):
                    return die(f"vtune: Error: The option `{flag}' requires a value.")
                value = argv[i]
            i += 1
            if flag == "-collect":
                o["collect"] = value
            elif flag == "-report":
                o["report"] = value
            elif flag in ("-result-dir", "-r"):
                o["result_dir"] = value
            elif flag == "-knob":
                o["knobs"].append(value)
            elif flag == "-report-knob":
                o["report_knobs"].append(value)
            elif flag == "-filter":
                o["filters"].append(value)
            elif flag in ("-duration", "-data-limit", "-target-pid", "-limit"):
                try:
                    num = float(value) if flag == "-duration" else int(value)
                except ValueError:
                    return die(f"vtune: Error: Invalid value `{value}' for option `{flag}'.")
                key = {"-duration": "duration", "-data-limit": "data_limit",
                       "-target-pid": "pid", "-limit": "limit"}[flag]
                o[key] = num
            else:
                key = {"-format": "format", "-csv-delimiter": "csv_delimiter",
                       "-report-output": "report_output", "-group-by": "group_by",
                       "-app-working-dir": "working_dir"}[flag]
                o[key] = value
            continue
        if arg.startswith("-"):
            return die(f"vtune: Error: Unknown option `{arg}'.")
        return die(f"vtune: Error: Unexpected argument `{arg}'.")
    return o


# -- model resolution ---------------------------------------------------------


def resolve_model(o: dict) -> tuple[str, dict[str, dict]]:
    """Return (default module name, function->spec model) for this target."""
    cmd = o["command"]
    target_name = Path(cmd[0]).name if cmd else "[Unknown]"
    if cmd:
        target = cmd[0]
        path: Path | None = None
        if os.sep in target:
            path = Path(o["working_dir"] or os.getcwd()) / target
        else:
            which = shutil.which(target)
            path = Path(which) if which else None
        if path is not None:
            sidecar = path.parent / (path.name + ".mockprofile.json")
            if sidecar.is_file():
                try:
                    data = json.loads(sidecar.read_text())
                except (OSError, json.JSONDecodeError):
                    data = None
                if isinstance(data, dict):
                    funcs = data.get("functions", {})
                    for sc in data.get("scenarios", []):
                        needles = sc.get("when_args_include", [])
                        if needles and all(n in cmd for n in needles):
                            funcs = sc.get("functions", funcs)
                            break
                    if funcs:
                        module = data.get("module") or target_name
                        return module, {name: dict(spec) for name, spec in funcs.items()}
    module = target_name
    return module, {
        "main": {"weight": 60, "source_file": "[Unknown]", "module": module},
        "__libc_start_main": {"weight": 5, "source_file": "[Unknown]", "module": "libc.so.6"},
        "[vmlinux]": {"weight": 35, "source_file": "[Unknown]", "module": "[vmlinux]"},
    }


def build_state(o: dict, wall: float, app_exit: int | None, start_unix: float) -> dict:
    module, model = resolve_model(o)
    total_w = sum(float(spec.get("weight", 0)) for spec in model.values()) or 1.0
    fixed = fixed_time()
    start = fixed if fixed is not None else start_unix
    # under MOCK_FIXED_TIME the stop timestamp is quantized so it is reproducible
    stop = start + (round(wall) if fixed is not None else wall)
    functions = {}
    for name, spec in model.items():
        cpu = float(spec.get("weight", 0)) / total_w * wall
        functions[name] = {
            "weight": spec.get("weight", 0),
            "cpu_time_sec": round(cpu, 6),
            "samples": int(round(cpu * 100)),  # 10 ms interval -> 100 samples/s
            "cpi": spec.get("cpi"),
            "cache_miss_rate": spec.get("cache_miss_rate"),
            "branch_miss_rate": spec.get("branch_miss_rate"),
            "source_file": spec.get("source_file", "[Unknown]"),
            "module": spec.get("module", module),
        }
    return {
        "analysis": o["collect"],
        "target": o["command"] if o["command"] else f"pid:{o['pid']}",
        "module": module,
        "wall_sec": round(wall, 6),
        "app_exit_code": app_exit,
        "start_time": start,
        "stop_time": stop,
        "sample_interval_ms": 10,
        "collector_type": "User-mode sampling and tracing",
        "functions": functions,
    }


def sorted_functions(state: dict) -> list[tuple[str, dict]]:
    return sorted(state["functions"].items(), key=lambda kv: (-kv[1]["cpu_time_sec"], kv[0]))


# -- report rendering ---------------------------------------------------------


def render_summary(state: dict) -> str:
    funcs = sorted_functions(state)
    cpu_total = sum(spec["cpu_time_sec"] for _, spec in funcs)
    out = [
        f"Elapsed Time: {state['wall_sec']:.3f}s",
        f"    CPU Time: {cpu_total:.3f}s",
        f"        Effective Time: {cpu_total:.3f}s",
        "        Spin Time: 0s",
        "        Overhead Time: 0s",
        "    Total Thread Count: 1",
        "    Paused Time: 0s",
        "",
        "Top Hotspots",
    ]
    table = [(name, spec["module"], spec["cpu_time_sec"]) for name, spec in funcs[:5]]
    if len(funcs) > 5:
        table.append(("[Others]", "N/A", sum(spec["cpu_time_sec"] for _, spec in funcs[5:])))
    rows = [
        (fn, mod, f"{v:.3f}s", f"{(v / cpu_total * 100 if cpu_total else 0):.1f}%")
        for fn, mod, v in table
    ]
    headers = ("Function", "Module", "CPU Time", "% of CPU Time(%)")
    widths = [
        max(len(h), *(len(r[ci]) for r in rows)) if rows else len(h)
        for ci, h in enumerate(headers)
    ]
    out.append(
        f"{headers[0]:<{widths[0]}}  {headers[1]:<{widths[1]}}  "
        f"{headers[2]:>{widths[2]}}  {headers[3]:>{widths[3]}}"
    )
    out.append("  ".join("-" * w for w in widths))
    for fn, mod, v, p in rows:
        out.append(f"{fn:<{widths[0]}}  {mod:<{widths[1]}}  {v:>{widths[2]}}  {p:>{widths[3]}}")
    out.append("Collection and Platform Info")
    target = state["target"]
    if isinstance(target, list):
        parts = [target[0], *(f'"{a}"' for a in target[1:])]
        out.append("    Application Command Line: " + " ".join(parts) + " ")
    out += [
        "    Operating System: 5.14.0-mock.x86_64",
        "    Computer Name: mockhost",
        "    Result Size: 4.0 MB ",
        f"    Collection start time: {fmt_utc(state['start_time'])}",
        f"    Collection stop time: {fmt_utc(state['stop_time'])}",
        f"    Collector Type: {state.get('collector_type', 'User-mode sampling and tracing')}",
        "    CPU",
        "        Name: Unknown",
        "        Frequency: 2.000 GHz",
        "        Logical CPU Count: 8",
        "",
        *HINT_BLOCK,
    ]
    return "\n".join(out) + "\n"


def render_hotspots(o: dict, state: dict) -> int:
    funcs = sorted_functions(state)
    # deterministic per-function start addresses, assigned by rank pre-filter
    addr = {name: f"0x{0x401000 + rank * 0x160:x}" for rank, (name, _) in enumerate(funcs)}
    for filt in o["filters"]:
        key, sep, val = filt.partition("=")
        if not sep or key not in ("function", "module"):
            return die(f"vtune: Error: Invalid filter `{filt}'.")
        if key == "function":
            funcs = [(n, s) for n, s in funcs if n == val]
        else:
            funcs = [(n, s) for n, s in funcs if s["module"] == val]
    if o["limit"] is not None:
        funcs = funcs[: o["limit"]]

    # -group-by module: real vtune aggregates rows by the grouping column and
    # replaces the leading "Function" column with it. Honor at least "module" so
    # the server's group_by param exercises the same shape the real tool emits.
    group_col = None
    if o["group_by"] == "module":
        agg: dict[str, float] = {}
        for _fn, spec in funcs:
            agg[spec["module"]] = agg.get(spec["module"], 0.0) + spec["cpu_time_sec"]
        funcs = [(mod, {"cpu_time_sec": t, "module": mod, "source_file": "", "_group": True})
                 for mod, t in sorted(agg.items(), key=lambda kv: (-kv[1], kv[0]))]
        group_col = "Module"

    fmt = o["format"] or "text"
    if fmt == "csv":
        delims = {"tab": "\t", "comma": ",", "semicolon": ";", "colon": ":"}
        name = o["csv_delimiter"] or "tab"  # empirical default: TAB
        if name not in delims:
            return die(f"vtune: Error: Invalid value `{name}' for option `-csv-delimiter'.")

        def num(v: float) -> str:
            return "0.0" if v == 0 else f"{v:.6f}"

        header = [group_col, *CSV_HEADER[1:]] if group_col else list(CSV_HEADER)
        buf = io.StringIO()
        writer = csv.writer(buf, delimiter=delims[name], lineterminator="\n")
        writer.writerow(header)
        for fn, spec in funcs:
            cpu = spec["cpu_time_sec"]
            writer.writerow([fn, num(cpu), num(cpu), "0.0", "0.0", spec["module"], fn,
                             spec["source_file"], addr.get(fn, "0x0")])
        return emit(o, buf.getvalue())
    if fmt != "text":
        return die(f"vtune: Error: Invalid value `{fmt}' for option `-format'.")

    def tval(v: float) -> str:
        return "0s" if v == 0 else f"{v:.3f}s"

    rows = [
        [fn, tval(spec["cpu_time_sec"]), tval(spec["cpu_time_sec"]), "0s", "0s",
         spec["module"], fn, spec["source_file"], addr[fn]]
        for fn, spec in funcs
    ]
    widths = [
        max(len(h), *(len(r[ci]) for r in rows)) if rows else len(h)
        for ci, h in enumerate(CSV_HEADER)
    ]
    right = {1, 2, 3, 4}  # time columns right-aligned per capture
    lines = [
        "  ".join(f"{h:>{widths[ci]}}" if ci in right else f"{h:<{widths[ci]}}"
                  for ci, h in enumerate(CSV_HEADER)),
        "  ".join("-" * w for w in widths),
    ]
    for r in rows:
        lines.append("  ".join(f"{c:>{widths[ci]}}" if ci in right else f"{c:<{widths[ci]}}"
                               for ci, c in enumerate(r)))
    return emit(o, "\n".join(lines) + "\n")


def emit(o: dict, text: str) -> int:
    if o["report_output"]:
        path = Path(o["report_output"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    else:
        sys.stdout.write(text)
        sys.stdout.flush()
    return 0


# -- actions ------------------------------------------------------------------


def do_collect(o: dict) -> int:
    analysis = o["collect"]
    if analysis not in KNOWN_ANALYSES:
        return die(f"vtune: Error: Cannot find analysis type `{analysis}'.")
    if not o["result_dir"]:
        return die("vtune: Error: No result directory is specified (use -result-dir).")
    if o["command"] is None and o["pid"] is None:
        return die("vtune: Error: The application to launch is not specified.")
    if o["command"] is not None and o["pid"] is not None:
        return die("vtune: Error: Cannot combine -target-pid with an application to launch.")

    fail = os.environ.get("MOCK_FAIL")
    if fail == "collect-perm":
        for line in PERM_FAIL_LINES:
            err(line)
        return 1
    if fail == "collect-hang":
        time.sleep(3600)

    rdir = Path(o["result_dir"]).absolute()
    rdir.mkdir(parents=True, exist_ok=True)
    err(
        "vtune: Collection started. To stop the collection, either press CTRL-C or enter "
        f"from another console window: vtune -r {rdir} -command stop."
    )

    start_unix = time.time()
    t0 = time.monotonic()
    app_exit: int | None = None
    if o["command"]:
        cmd = o["command"]
        try:
            if o["duration"] is not None:
                # -duration caps the collection: the app is stopped at the deadline
                proc = subprocess.Popen(cmd, cwd=o["working_dir"] or None)
                try:
                    app_exit = proc.wait(timeout=o["duration"])
                except subprocess.TimeoutExpired:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
            else:
                app_exit = subprocess.run(cmd, cwd=o["working_dir"] or None).returncode
        except FileNotFoundError:
            err("vtune: Collection stopped.")
            return die(
                f"vtune: Error: Cannot start the application `{cmd[0]}': "
                "No such file or directory."
            )
    else:
        time.sleep(o["duration"] if o["duration"] is not None else 1.0)
    wall = time.monotonic() - t0

    err("vtune: Collection stopped.")
    err(f"vtune: Using result path `{rdir}'")
    if app_exit is not None and app_exit != 0:
        err(f"vtune: Warning: Target application exited with code {app_exit}.")
    # Machine-readable marker (mock only) so the server can surface the target's
    # real exit — real vtune does not report the app's exit code by default.
    err(f"profiler-mcp-mock: app-exit-code={'' if app_exit is None else app_exit}")

    state = build_state(o, wall, app_exit, start_unix)
    (rdir / "samples.json").write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")
    code = ANALYSIS_CODES.get(analysis) or "".join(c for c in analysis if c.isalnum())[:4]
    (rdir / f"r000{code}.vtune").write_text("mock vtune result marker\n")

    if not o["quiet"]:
        for pct, action in PROGRESS:
            err(f"vtune: Executing actions {pct:2d} %" + (f" {action}" if action else ""))
        sys.stdout.write(render_summary(state))
        sys.stdout.flush()
        err("vtune: Executing actions 100 % Generating a report")
        err("vtune: Executing actions 100 % done")
    return 0


def do_report(o: dict) -> int:
    rtype = o["report"]
    if not o["result_dir"]:
        return die("vtune: Error: No result directory is specified (use -result-dir).")
    if o["command"] is not None:
        return die("vtune: Error: Cannot combine -report with an application to launch.")
    rdir = Path(o["result_dir"]).absolute()
    state_path = rdir / "samples.json"
    if not rdir.is_dir() or not state_path.is_file():
        return die(f"vtune: Error: Cannot open result path `{rdir}'.")
    if rtype not in ("summary", "hotspots"):
        return die(f"vtune: Error: Cannot find report `{rtype}'.")
    if os.environ.get("MOCK_FAIL") == "report-empty":
        return emit(o, "")
    try:
        state = json.loads(state_path.read_text())
    except (OSError, json.JSONDecodeError):
        return die(f"vtune: Error: Cannot open result path `{rdir}'. The result is corrupted.")

    fixed = fixed_time()
    if fixed is not None:
        state["start_time"] = fixed
        state["stop_time"] = fixed + round(state.get("wall_sec", 0))
    if rtype == "summary":
        return emit(o, render_summary(state))
    return render_hotspots(o, state)


def main(argv: list[str] | None = None) -> int:
    o = parse_args(sys.argv[1:] if argv is None else argv)
    if isinstance(o, int):
        return o
    if o["version"]:
        sys.stdout.write(VERSION_TEXT)
        rc = 0
    elif o["help"]:
        sys.stdout.write(HELP_TEXT)
        rc = 0
    elif o["collect"] and o["report"]:
        rc = die("vtune: Error: Cannot combine -collect and -report in one invocation.")
    elif o["collect"]:
        rc = do_collect(o)
    elif o["report"]:
        rc = do_report(o)
    else:
        rc = die("vtune: Error: No action option is specified. Use vtune -help.")
    if rc == 0 and os.environ.get("MOCK_FAIL") == "bad-exit":
        rc = 41
    return rc


if __name__ == "__main__":
    sys.exit(main())
