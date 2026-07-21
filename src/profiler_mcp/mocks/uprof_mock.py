#!/usr/bin/env python3
"""Mock AMDuProfCLI — byte-realistic stdout and CSV per docs/research/captures-uprof.md.

Standalone, stdlib-only; invoked as `python uprof_mock.py <subcommand> ...`.
It really runs the target application (stdout/stderr passed through, exit code
captured) and synthesizes deterministic samples from `<target>.mockprofile.json`
when that sidecar exists, else from a generic fallback model. No randomness.

Env contract (docs/DESIGN.md):
  MOCK_FAIL        collect-perm | collect-hang | report-empty | bad-exit
  MOCK_FIXED_TIME  unix seconds; pins every emitted timestamp (rendered as UTC
                   so fixture comparisons are byte-exact regardless of host TZ)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import zlib
from pathlib import Path

VERSION = "5.0.1479.0"
SELF = os.path.realpath(__file__)

SESSION_TYPES = {
    "tbp": "TBP",
    "hotspots": "Hotspots",
    "assess": "EBP",
    "assess_ext": "EBP",
    "data_access": "EBP",
    "inst_access": "EBP",
    "branch": "EBP",
    "cpi": "EBP",
    "threading": "Threading",
    "ibs": "IBS",
    "memory": "EBP",
    "energy": "EBP",
    "overview": "Overview",
}
DISPLAY_TYPES = {
    "hotspots": "Hotspots",
    "tbp": "Time-based Sampling",
    "assess": "Assess Performance",
}
SELECTED_VIEWS = {"assess": "Overall Assessment"}

CPU_DETAILS = "Family(0x19), Model(0x44), Number of Cores(12)"
OS_DETAILS = "Linux Ubuntu 24.04.1 LTS-64 Kernel:6.11.0-25-generic"

# No public verbatim capture of uProf's paranoid refusal exists; this mirrors the
# perf_event_paranoid guidance the real tool and its docs give.
PERM_ERROR = (
    "Error: perf_event_open syscall failed (Permission denied).\n"
    "The kernel restricts unprivileged CPU profiling:"
    " /proc/sys/kernel/perf_event_paranoid is 4.\n"
    "Either run as root or lower the paranoid level:\n"
    "    echo 2 | sudo tee /proc/sys/kernel/perf_event_paranoid\n"
    "Profiling failed to start."
)

# Fallback when no <target>.mockprofile.json sidecar exists: plausible shares only.
GENERIC_FUNCTIONS = {
    "main": {"weight": 60, "cpi": 1.1},
    "__libc_start_call_main": {
        "weight": 5,
        "cpi": 1.0,
        "module": "/usr/lib/x86_64-linux-gnu/libc.so.6",
    },
    "[vmlinux]": {"weight": 35, "cpi": 2.0, "module": "[vmlinux]"},
}

COLLECT_VALUE_FLAGS = {
    "--config": "config",
    "-o": "out",
    "--output-dir": "out",
    "--log-path": "log",
    "-d": "duration",
    "-w": "wdir",
    "-e": "event",
    "-p": "pid",
}
COLLECT_BOOL_FLAGS = {"-g": "callstack"}

REPORT_VALUE_FLAGS = {
    "-i": "input",
    "--report-output": "report_output",
    "--cutoff": "cutoff",
    "--group-by": "group_by",
}
REPORT_BOOL_FLAGS = {"--detail": "detail", "--ignore-system-module": "ignore_system"}

TIMECHART_VALUE_FLAGS = {
    "--event": "event",
    "-o": "out",
    "--output-dir": "out",
    "--interval": "interval",
    "--duration": "duration",
    "--format": "format",
    "--affinity": "affinity",
}


def say(line: str = "") -> None:
    print(line, flush=True)


def fail_mode(kind: str) -> bool:
    return os.environ.get("MOCK_FAIL") == kind


def die(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def finish(code: int = 0) -> None:
    # bad-exit: normal-looking output, then a nonzero exit the servers must surface
    sys.exit(41 if fail_mode("bad-exit") and code == 0 else code)


def fixed_time() -> float | None:
    raw = os.environ.get("MOCK_FIXED_TIME")
    return float(raw) if raw else None


def now() -> float:
    fixed = fixed_time()
    return time.time() if fixed is None else fixed


def tm(t: float) -> time.struct_time:
    return time.localtime(t) if fixed_time() is None else time.gmtime(t)


def stamp(t: float) -> str:
    return time.strftime("%b-%d-%Y_%H-%M-%S", tm(t))


def q(v: object) -> str:
    return f'"{v}"'


def take_flags(
    tokens: list[str],
    value_flags: dict[str, str],
    bool_flags: dict[str, str],
) -> dict:
    """Strict flag parser: an unknown option before the target argv is an error."""
    opts: dict = {"events": [], "command": []}
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if not tok.startswith("-"):
            break
        if tok in bool_flags:
            opts[bool_flags[tok]] = True
            i += 1
        elif tok in value_flags:
            if i + 1 >= len(tokens):
                die(f"Error: option '{tok}' requires a value")
            if value_flags[tok] == "event":
                opts["events"].append(tokens[i + 1])
            else:
                opts[value_flags[tok]] = tokens[i + 1]
            i += 2
        else:
            die(f"Error: Invalid option: '{tok}'")
    opts["command"] = tokens[i:]
    return opts


def resolve_target(exe: str, wdir: str | None) -> Path:
    p = Path(exe)
    if p.is_absolute():
        return p
    candidate = Path(wdir or os.getcwd()) / p
    if candidate.exists():
        return candidate.absolute()
    found = shutil.which(exe)
    return Path(found) if found else candidate.absolute()


def load_model(target: Path | None, module: str, argv: list[str]) -> tuple[str, dict]:
    if target is not None:
        sidecar = Path(str(target) + ".mockprofile.json")
        if sidecar.is_file():
            try:
                spec = json.loads(sidecar.read_text())
            except (OSError, json.JSONDecodeError):
                spec = {}
            funcs = dict(spec.get("functions", {}))
            for scenario in spec.get("scenarios", []):
                need = scenario.get("when_args_include", [])
                if need and all(s in argv for s in need):
                    funcs = dict(scenario.get("functions", funcs))
                    break
            if funcs:
                return module, funcs
    return module, GENERIC_FUNCTIONS


def synthesize(module: str, funcs: dict, wall_sec: float) -> list[dict]:
    total_weight = sum(float(f.get("weight", 0)) for f in funcs.values()) or 1.0
    rows: list[dict] = []
    for name, spec in funcs.items():
        cpu = wall_sec * float(spec.get("weight", 0)) / total_weight
        n_samples = round(cpu * 100)  # 10 ms timer -> 100 samples/s
        if n_samples < 1:
            continue
        rows.append({
            "function": name,
            "module": spec.get("module", module),
            "cpu_time_sec": round(cpu, 4),
            "samples": n_samples,
            "cpi": spec.get("cpi"),
            "cache_miss_rate": spec.get("cache_miss_rate"),
            "branch_miss_rate": spec.get("branch_miss_rate"),
            "source_file": spec.get("source_file"),
        })
    rows.sort(key=lambda r: (-r["cpu_time_sec"], r["function"]))
    return rows


# -- collect / profile -------------------------------------------------------


def run_collect(tokens: list[str]) -> Path:
    opts = take_flags(tokens, COLLECT_VALUE_FLAGS, COLLECT_BOOL_FLAGS)
    config = str(opts.get("config", "tbp"))
    say(SELF)  # the real binary echoes its own resolved path as line 1
    if fail_mode("collect-perm"):
        print(PERM_ERROR, file=sys.stderr)
        sys.exit(1)
    say("Profiling started")
    if fail_mode("collect-hang"):
        time.sleep(3600)  # ignores -d so timeout handling can be exercised

    duration = float(opts["duration"]) if "duration" in opts else None
    wdir = opts.get("wdir")
    start = now()
    t0 = time.monotonic()
    command: list[str] = opts["command"]
    app_exit: int | None = 0

    if "pid" in opts:
        if command:
            die("Error: cannot pass both -p and a target application")
        wall = duration if duration is not None else 1.0
        time.sleep(min(wall, 2.0))  # cap real sleep; synthesis uses the requested duration
        target_label = f"pid{opts['pid']}"
        module = f"/proc/{opts['pid']}/exe"
        sidecar_base: Path | None = None
        app_exit = None
    else:
        if not command:
            die("Error: no target application specified")
        sys.stdout.flush()
        sys.stderr.flush()
        try:
            proc = subprocess.run(command, cwd=wdir, timeout=duration)
            app_exit = proc.returncode
        except FileNotFoundError:
            die(f"Error: failed to launch target application '{command[0]}'")
        except subprocess.TimeoutExpired:
            app_exit = 0  # duration elapsed: collection stops, app is stopped
        wall = time.monotonic() - t0
        target_label = command[0]
        sidecar_base = resolve_target(command[0], wdir)
        module = str(sidecar_base)

    app_name = os.path.splitext(Path(target_label).name)[0] or "app"
    session_type = SESSION_TYPES.get(config, config.capitalize())
    base = Path(opts.get("out", os.getcwd()))
    session = (base / f"AMDuProf-{app_name}-{session_type}_{stamp(start)}").absolute()
    session.mkdir(parents=True, exist_ok=True)
    (session / "cpu.caperf").write_bytes(b"AMDuProf mock raw data (caperf stub)\n")

    module, funcs = load_model(sidecar_base, module, command)
    end = start if fixed_time() is not None else start + wall
    data = {
        "version": VERSION,
        "config": config,
        "session_type": session_type,
        "target_path": target_label,
        "target_args": command[1:] if command else [],
        "working_dir": str(Path(wdir or os.getcwd()).absolute()),
        "collect_command": " ".join(sys.argv),
        "call_stack": bool(opts.get("callstack")),
        "start_time": start,
        "end_time": end,
        "wall_sec": round(wall, 4),
        "app_exit_code": app_exit,
        "interval_ms": 10,
        "functions": synthesize(module, funcs, wall),
    }
    (session / "samples.json").write_text(json.dumps(data, indent=1))
    if app_exit is not None and app_exit != 0:
        print(f"Warning: target application exited with code {app_exit}", file=sys.stderr)
    # Machine-readable marker (mock only, on stderr so it never disturbs the
    # stdout path lines) so the server can surface the target's real exit.
    print(f"profiler-mcp-mock: app-exit-code={'' if app_exit is None else app_exit}",
          file=sys.stderr)
    say("Profiling (data collection) completed ")  # trailing space is byte-verified (5.0)
    say(f"Generated data files path: {session}")
    return session


# -- report ------------------------------------------------------------------


def render_report(data: dict, session: Path, cutoff: int, ignore_system: bool,
                  report_cmd: str) -> str:
    config = data.get("config", "tbp")
    funcs = list(data.get("functions", []))
    if ignore_system:
        funcs = [f for f in funcs
                 if not str(f["module"]).startswith(("/usr/", "/lib", "["))]
    total = sum(f["cpu_time_sec"] for f in funcs)
    comm = Path(data.get("target_path", "app")).name[:15]  # Linux comm truncation
    pid = 100000 + zlib.crc32(comm.encode()) % 900000  # deterministic stand-in PID
    call_stack = "True" if data.get("call_stack") else "False"
    duration_txt = f"{data['wall_sec']:.3f} seconds"
    interval = "1.000 milliseconds" if config == "tbp" else "10.000 milliseconds"
    args = " ".join(data.get("target_args", []))
    display_type = DISPLAY_TYPES.get(config, data.get("session_type", config.capitalize()))

    lines = [
        "",
        f'"AMD uProf (Version:{VERSION})"',
        "PERFORMANCE ANALYSIS REPORT",
        "",
        "EXECUTION",
        f"Target Path:,{q(data['target_path'])}",
        f"Command Line Arguments:,{q(args)}" if args else "Command Line Arguments:",
        f"Working Directory:,{q(data['working_dir'])}",
        "Environment Variables:",
        f"CPU Details:,{q(CPU_DETAILS)}",
        f"Operating System:,{q(OS_DETAILS)}",
        f"Collect Command:,{q(data['collect_command'])}",
        f"Report Command:,{q(report_cmd)}",
        "",
        "PROFILE DETAILS",
        f"Profile Session Type:,{q(display_type)}",
        'Profile Scope:,"Single Application"',
        'CPU Mask:,"0-11"',
        'CPU Affinity Mask:,"0-11"',
        f"Profile Start Time:,{q(time.asctime(tm(data['start_time'])))}",
        f"Profile End Time:,{q(time.asctime(tm(data['end_time'])))}",
        f"Profile Duration:,{q(duration_txt)}",
        f"Data Folder:,{q(session)}",
        'Virtual Machine:,"No"',
    ]
    if config == "tbp":
        lines += [
            f'Call Stack Sampling:,"{call_stack}"',
            'Call Stack Overcome frame-pointer omission:,"False"',
            'Call Stack Size(Bytes):,"1024"',
        ]
    else:
        lines += [
            'Timer Interval:,"10ms"',
            'Profiling Signal:,"27"',
            f'Call Stack Sampling:,"{call_stack}"',
            'Call Stack Overcome frame-pointer omission:,"False"',
            'Call Stack Unwind Depth:,"32"',
        ]
    events_desc = "CPU Time is the time in which the CPU core is executing the code."
    lines += [
        f"Selected View:,{q(SELECTED_VIEWS.get(config, 'Time based hotspots'))}",
        "",
        "MONITORED EVENTS",
        "TBP Events:,Name,Interval,Description",
        f',"CPU_TIME","{interval}","{events_desc}"',
        "",
        "",
        "APPLICATION PERFORMANCE SNAPSHOT",
        'Number Of Threads,"1"',
        "",
        "",
        '"10 HOTTEST FUNCTIONS (Sort Event - CPU_TIME)"',
    ]
    if config == "tbp":  # tbp reports omit the Inclusive Time column (5.0 capture)
        lines.append('FUNCTION,"CPU_TIME" (seconds),Module')
        for f in funcs[:cutoff]:
            lines.append(f"{q(f['function'])},{f['cpu_time_sec']:.4f},{q(f['module'])}")
    else:
        lines.append('FUNCTION,"CPU_TIME" (seconds),Inclusive Time (seconds),Module')
        for f in funcs[:cutoff]:
            v = f["cpu_time_sec"]
            lines.append(f"{q(f['function'])},{v:.4f},{v:.4f},{q(f['module'])}")
    process_name = f"{comm} (PID:{pid})"
    lines += [
        "",
        '"10 HOTTEST PROCESSES (Sort Event - CPU_TIME)"',
        'PROCESS,"CPU_TIME" (seconds)',
        f"{q(process_name)},{total:.4f}",
        "",
        '"10 HOTTEST MODULES (Sort Event - CPU_TIME)"',
        'MODULE,"CPU_TIME" (seconds)',
    ]
    per_module: dict[str, float] = {}
    for f in funcs:
        per_module[f["module"]] = per_module.get(f["module"], 0.0) + f["cpu_time_sec"]
    for mod, v in sorted(per_module.items(), key=lambda kv: (-kv[1], kv[0]))[:cutoff]:
        lines.append(f"{q(mod)},{v:.4f}")
    lines += [
        "",
        '"10 HOTTEST THREADS (Sort Event - CPU_TIME)"',
        'THREAD,THREAD ID,"CPU_TIME" (seconds)',
        f'{q(process_name)},"{pid}",{total:.4f}',
    ]
    # File begins with a lone LF and ends WITHOUT a trailing newline (byte-verified).
    return "\n".join(lines)


def emit_report(session: Path, opts: dict, report_cmd: str) -> None:
    samples = session / "samples.json"
    if not samples.is_file():
        die(f"Error: no profile data found in '{session}'")
    data = json.loads(samples.read_text())
    say("Translation started ...")
    say("Translation finished")
    say("Generated database file : cpu")
    say("Report generation started...")
    say("Generating report file...")
    say("")
    say("Report generation completed...")
    say("")
    out = Path(opts["report_output"]) if "report_output" in opts else session / "report.csv"
    if out.is_dir():
        out = out / "report.csv"
    try:
        cutoff = int(opts.get("cutoff", 10))
    except ValueError:
        die(f"Error: invalid --cutoff value '{opts.get('cutoff')}'")
    if fail_mode("report-empty"):
        text = ""
    else:
        text = render_report(data, session, cutoff, bool(opts.get("ignore_system")), report_cmd)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, newline="\n")
    say(f"Generated report file: {out}")


def do_report(tokens: list[str]) -> None:
    opts = take_flags(tokens, REPORT_VALUE_FLAGS, REPORT_BOOL_FLAGS)
    if opts["command"]:
        die(f"Error: unexpected argument '{opts['command'][0]}'")
    if "input" not in opts:
        die("Error: input directory not specified (-i)")
    say(SELF)
    emit_report(Path(opts["input"]).absolute(), opts, " ".join(sys.argv))
    finish(0)


# -- timechart ---------------------------------------------------------------


def timechart_counters(categories: list[str]) -> list[tuple[str, str, str, str, float]]:
    out: list[tuple[str, str, str, str, float]] = []
    for cat in categories:
        if cat == "power":
            out += [(f"core{i}-power", "Power", "W",
                     f"Core{i}-Average Power reported in Watts.",
                     2.0 if i == 0 else 0.1 + 0.05 * i) for i in range(6)]
        elif cat == "frequency":
            out += [(f"core{i}-frequency", "Frequency", "MHz",
                     f"Core{i}-Effective Frequency reported in MHz.",
                     3800.0 - 50.0 * i) for i in range(6)]
        elif cat == "temperature":
            out.append(("socket0-temperature", "Temperature", "C",
                        "Socket0-Average Temperature reported in Celsius.", 46.0))
        elif cat == "voltage":
            out.append(("socket0-voltage", "Voltage", "V",
                        "Socket0-Average Core Voltage reported in Volts.", 1.05))
        elif cat == "current":
            out.append(("socket0-current", "Current", "A",
                        "Socket0-Average Core Current reported in Amperes.", 4.5))
        elif cat == "energy":
            out.append(("socket0-energy", "Energy", "J",
                        "Socket0-Average Energy reported in Joules.", 12.0))
        elif cat == "dvfs":
            out += [(f"core{i}-p-state", "DVFS", "P-State",
                     f"Core{i}-Current P-State.", 1.0) for i in range(6)]
        else:
            out.append((f"{cat}-metric", cat.capitalize(), "", f"{cat} metric.", 1.0))
    return out


def tc_timestamp(t_ms: int) -> str:
    t = tm(t_ms // 1000)
    return f"{t.tm_hour}:{t.tm_min}:{t.tm_sec}:{t_ms % 1000}"  # H:M:S:ms, unpadded


def render_timechart(counters: list[tuple[str, str, str, str, float]], interval: int,
                     records: int, start: float, command: list[str], wdir: str) -> str:
    exe = command[0] if command else ""
    args = " ".join(command[1:]) if command else ""
    lines = [
        "AMDPROFILER POWER PROFILE REPORT",
        "",
        f"AMDuProfCLI Version {VERSION},",
        "",
        "LAUNCHED APPLICATION DETAILS",
        f"Target Path:,{exe},",
        f"Command Line Arguments:,{args},",
        f"Working Directory:,{wdir},",
        "CPU Core Affinity Mask:,,",
        "",
        "PROFILE DETAILS",
        "CPU Details:,Family(0x19) Model(0x44)",
        f"Sampling Interval:,{interval} milli-seconds",
        f"Profile Start Time:,{stamp(start)},",
        "",
        "PROFILED COUNTERS",
        "COUNTER ID,NAME,CATEGORY,UNIT,DESCRIPTION",
    ]
    for ci, (name, cat, unit, desc, _) in enumerate(counters):
        lines.append(f"{38 + 2 * ci}.,{name},{cat},{unit},{desc}")
    lines += ["", "PROFILE RECORDS",
              "RecordId,Timestamp," + ",".join(c[0] for c in counters)]
    base_ms = int(start * 1000)
    for r in range(1, records + 1):
        # deterministic ripple around each counter's base value; %8.2f per capture
        vals = ",".join(f"{c[4] + 0.01 * ((r * 7 + ci * 13) % 37):8.2f}"
                        for ci, c in enumerate(counters))
        lines.append(f"{r},{tc_timestamp(base_ms + (r - 1) * interval)},{vals}")
    return "\n".join(lines) + "\n"


def do_timechart(tokens: list[str]) -> None:
    opts = take_flags(tokens, TIMECHART_VALUE_FLAGS, {})
    categories = [c for ev in opts["events"] for c in ev.split(",") if c and "=" not in c]
    if not categories:
        die("Error: no event specified (--event)")
    try:
        interval = int(opts.get("interval", 100))
        duration = float(opts.get("duration", 10))
    except ValueError:
        die("Error: invalid --interval/--duration value")
    say(SELF)
    if fail_mode("collect-perm"):
        print(PERM_ERROR, file=sys.stderr)
        sys.exit(1)
    say("Profiling started...")  # timechart keeps the ellipsis (4.1/5.x captures)
    if fail_mode("collect-hang"):
        time.sleep(3600)
    start = now()
    command: list[str] = opts["command"]
    if command:
        sys.stdout.flush()
        sys.stderr.flush()
        try:
            subprocess.run(command, timeout=duration or None)
        except FileNotFoundError:
            die(f"Error: failed to launch target application '{command[0]}'")
        except subprocess.TimeoutExpired:
            pass
    else:
        time.sleep(min(duration, 2.0))  # cap real sleep; synthesize all requested records
    records = max(1, int(duration * 1000 / max(interval, 1)))
    step = max(1, records // 20)  # bounded progress breadcrumbs
    for i in range(0, records, step):
        print(f"\rProfile Elapse Time in ms: {i * interval}", end="")
    print(flush=True)
    say("Profile finished")
    app_name = os.path.splitext(Path(command[0]).name)[0] if command else "system"
    base = Path(opts.get("out", os.getcwd()))
    session = (base / f"AMDuProf-{app_name}-Timechart_{stamp(start)}").absolute()
    session.mkdir(parents=True, exist_ok=True)
    csv_path = session / "timechart.csv"
    if fail_mode("report-empty"):
        csv_path.write_text("")
    else:
        counters = timechart_counters(categories)
        csv_path.write_text(
            render_timechart(counters, interval, records, start, command, os.getcwd()),
            newline="\n",
        )
    say(f"Generated data files path: {session}")
    say(f"Live Profile Output file : {csv_path}")  # space before colon is verbatim
    finish(0)


# -- info / version ----------------------------------------------------------

# No public verbatim `info --system` capture exists (docs show screenshots);
# this block is plausible-shaped only, keyed 'Name : value' for easy parsing.
SYSTEM_INFO = """\
System Details:
    Processor Name      : AMD Ryzen 5 7535HS with Radeon Graphics
    CPU Family          : 0x19
    CPU Model           : 0x44
    CPU Stepping        : 0x1
    Number of Sockets   : 1
    Number of Cores     : 6
    Number of Threads   : 12
    Base Frequency      : 3300 MHz
    Hypervisor Enabled  : No
    OS Name             : Linux
    Kernel Version      : 6.11.0-25-generic
    perf_event_paranoid : 2
    uProf Version       : 5.0.1479.0"""

# Keep in sync with KNOWN_CONFIGS in src/profiler_mcp/uprof/cli.py.
COLLECT_CONFIGS = """\
Supported Collect Configurations:
    tbp          Time-based Sampling
    hotspots     Hotspots Analysis
    assess       Assess Performance
    assess_ext   Assess Performance (Extended)
    data_access  Data Access Analysis
    inst_access  Instruction Access Analysis
    branch       Branch Analysis
    cpi          Cycles Per Instruction
    threading    Thread Concurrency
    ibs          Instruction-Based Sampling
    memory       Memory Analysis
    energy       Energy Analysis
    gpu          GPU Analysis
    overview     System Overview"""


def do_info(tokens: list[str]) -> None:
    say(SELF)
    if tokens and tokens[0] == "--system":
        say(SYSTEM_INFO)
    elif len(tokens) >= 2 and tokens[0] == "--list" and tokens[1] == "collect-configs":
        say(COLLECT_CONFIGS)
    elif len(tokens) >= 2 and tokens[0] == "--list":
        say(f"Supported {tokens[1]}:")
    else:
        die("Error: info requires --system or --list <type>")
    finish(0)


def do_version() -> None:
    say(SELF)
    say(f"AMDuProfCLI Version {VERSION}")
    finish(0)


def main() -> None:
    args = sys.argv[1:]
    if not args:
        die("Error: no command specified. See 'AMDuProfCLI --help'.")
    cmd = args[0]
    if cmd == "--version":
        do_version()
    elif cmd == "collect":
        run_collect(args[1:])
        finish(0)
    elif cmd == "profile":
        # one-shot collect + report: BOTH 'Generated ...' lines in a single stdout
        session = run_collect(args[1:])
        emit_report(session, {}, f"{sys.argv[0]} report -i {session}")
        finish(0)
    elif cmd == "report":
        do_report(args[1:])
    elif cmd == "timechart":
        do_timechart(args[1:])
    elif cmd == "info":
        do_info(args[1:])
    else:
        die(f"Error: unknown command '{cmd}'")


if __name__ == "__main__":
    main()
