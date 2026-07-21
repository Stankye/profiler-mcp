"""Parsers for AMDuProfCLI stdout and CSV output files.

Shapes follow the byte-verified captures in docs/research/captures-uprof.md
(uProf 5.0.1479 report.csv / timechart.csv, 4.x-5.x stdout transcripts).
Files are line-oriented sections, not one rectangular table, so csv.reader is
applied per line; every section terminates at the first blank line.
"""

from __future__ import annotations

import csv
import re

from ..core.models import HotspotRow

# Exact regexes used by AMDResearch/intellikit against `profile` stdout (MIT).
_SESSION_DIR_RE = re.compile(r"Generated data files path: (.*)")
_REPORT_FILE_RE = re.compile(r"Generated report file: (.*)")

_HOTTEST_RE = re.compile(r"^\d+ HOTTEST (FUNCTIONS|PROCESSES|MODULES|THREADS) "
                         r"\(Sort Event - (.+)\)$")
_VERSION_LINE_RE = re.compile(r"[Vv]ersion[:\s]+(\d+(?:\.\d+)+)")
_VERSION_BARE_RE = re.compile(r"\d+(?:\.\d+)+")


def _row(line: str) -> list[str]:
    try:
        return next(csv.reader([line]))
    except (csv.Error, StopIteration):
        return [line]


def _section(lines: list[str], header: str) -> list[str]:
    """Lines of the section that starts right after an exact `header` line."""
    try:
        start = lines.index(header) + 1
    except ValueError:
        return []
    out: list[str] = []
    for ln in lines[start:]:
        if not ln.strip():
            break
        out.append(ln)
    return out


def _kv(section: list[str]) -> dict[str, str]:
    """'Key:,"value"' rows -> dict; tolerates trailing commas and bare 'Key:' rows."""
    out: dict[str, str] = {}
    for ln in section:
        fields = _row(ln)
        while fields and not fields[-1]:
            fields.pop()
        if not fields or not fields[0]:
            continue
        out[fields[0].rstrip(":")] = fields[1] if len(fields) > 1 else ""
    return out


def parse_collect_stdout(text: str) -> dict:
    session = _SESSION_DIR_RE.search(text)
    report = _REPORT_FILE_RE.search(text)
    return {
        "session_dir": session.group(1).strip() if session else None,
        "report_path": report.group(1).strip() if report else None,
    }


def _hottest_sections(lines: list[str]) -> dict[str, tuple[str, list[str], list[str]]]:
    """Section name ('FUNCTIONS', ...) -> (sort_event, column_fields, data_lines).

    The '"10 HOTTEST ..."' header line is itself one quoted CSV field.
    """
    found: dict[str, tuple[str, list[str], list[str]]] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        match = _HOTTEST_RE.match(_row(line)[0]) if line.startswith('"') else None
        if match and i + 1 < len(lines):
            cols = _row(lines[i + 1])
            data: list[str] = []
            j = i + 2
            while j < len(lines) and lines[j].strip():
                data.append(lines[j])
                j += 1
            found[match.group(1)] = (match.group(2), cols, data)
            i = j
        else:
            i += 1
    return found


def _parse_functions(event: str, cols: list[str], data: list[str]) -> list[HotspotRow]:
    # 5.x hotspots: FUNCTION,"CPU_TIME" (seconds),Inclusive Time (seconds),Module
    # 5.x tbp omits the Inclusive column; pre-5.0 omitted ' (seconds)'.
    has_inclusive = any("Inclusive" in c for c in cols)
    value_col = cols[1] if len(cols) > 1 else ""
    metric = "cpu_time_sec" if "CPU_TIME" in value_col else event.lower()
    raw: list[tuple[str, str, float, float | None]] = []
    for ln in data:
        fields = _row(ln)
        if len(fields) < 3:
            continue
        try:
            value = float(fields[1])
        except ValueError:
            continue
        inclusive: float | None = None
        if has_inclusive and len(fields) >= 4:
            try:
                inclusive = float(fields[2])
            except ValueError:
                inclusive = None
        raw.append((fields[0], fields[-1], value, inclusive))
    total = sum(entry[2] for entry in raw)
    rows: list[HotspotRow] = []
    for function, module, value, inclusive in raw:
        row: HotspotRow = {
            "function": function,
            "module": module,
            "metric": metric,
            "value": value,
            "percent": round(value / total * 100, 2) if total else 0.0,
        }
        if inclusive is not None:
            row["extra"] = {"inclusive_sec": inclusive}
        rows.append(row)
    return rows


def _parse_simple(name: str, data: list[str]) -> list[dict]:
    out: list[dict] = []
    for ln in data:
        fields = _row(ln)
        if len(fields) < 2:
            continue
        try:
            value = float(fields[-1])
        except ValueError:
            continue
        entry: dict = {"name": fields[0], "value": value}
        if name == "THREADS" and len(fields) >= 3:
            entry["thread_id"] = fields[1]
        out.append(entry)
    return out


def parse_report_csv(text: str) -> dict:
    lines = text.split("\n")
    notes: list[str] = []
    if not text.strip():
        notes.append("report file is empty")

    execution = _kv(_section(lines, "EXECUTION"))
    profile_details = _kv(_section(lines, "PROFILE DETAILS"))

    duration_sec: float | None = None
    duration_raw = profile_details.get("Profile Duration", "")
    if duration_raw:
        try:
            duration_sec = float(duration_raw.split()[0])
        except ValueError:
            notes.append(f"unparseable Profile Duration: {duration_raw!r}")

    monitored_events: list[str] = []
    for ln in _section(lines, "MONITORED EVENTS"):
        fields = _row(ln)
        # data rows start with an empty field: ,"CPU_TIME","10.000 milliseconds",...
        if len(fields) >= 2 and not fields[0] and fields[1]:
            monitored_events.append(fields[1])

    hottest = _hottest_sections(lines)
    if "FUNCTIONS" in hottest:
        hottest_functions = _parse_functions(*hottest["FUNCTIONS"])
    else:
        hottest_functions = []
        if not notes:
            notes.append("no HOTTEST FUNCTIONS section found")

    return {
        "execution": execution,
        "profile_details": profile_details,
        "duration_sec": duration_sec,
        "monitored_events": monitored_events,
        "hottest_functions": hottest_functions,
        "hottest_processes": _parse_simple("PROCESSES", hottest.get("PROCESSES", ("", [], []))[2]),
        "hottest_modules": _parse_simple("MODULES", hottest.get("MODULES", ("", [], []))[2]),
        "hottest_threads": _parse_simple("THREADS", hottest.get("THREADS", ("", [], []))[2]),
        "notes": notes,
    }


def parse_timechart_csv(text: str) -> dict:
    lines = text.split("\n")
    details = _kv(_section(lines, "PROFILE DETAILS"))

    counters: dict[str, dict[str, float]] = {}
    samples = 0
    try:
        header_idx = lines.index("PROFILE RECORDS") + 1
    except ValueError:
        header_idx = -1
    if 0 < header_idx < len(lines):
        names = [c.strip() for c in _row(lines[header_idx])[2:]]
        series: dict[str, list[float]] = {n: [] for n in names}
        for ln in lines[header_idx + 1:]:
            if not ln.strip():
                break
            fields = _row(ln)
            if len(fields) < 3:
                continue
            counted = False
            for name, value in zip(names, fields[2:], strict=False):
                try:
                    series[name].append(float(value.strip()))
                    counted = True
                except ValueError:
                    pass
            if counted:
                samples += 1
        for name, values in series.items():
            if values:
                counters[name] = {
                    "min": min(values),
                    "max": max(values),
                    "mean": round(sum(values) / len(values), 4),
                    "last": values[-1],
                }
    return {"counters": counters, "samples": samples, "details": details}


def parse_version_output(text: str) -> str:
    match = _VERSION_LINE_RE.search(text)
    if match:
        return match.group(1)
    match = _VERSION_BARE_RE.search(text)
    if match:
        return match.group(0)
    for ln in text.splitlines():
        if ln.strip():
            return ln.strip()
    return ""
