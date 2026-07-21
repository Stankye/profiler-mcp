"""Parsers for Intel VTune CLI report output.

Grounded in verbatim captures (docs/research/captures-vtune.md, mirrored in
tests/fixtures/vtune_*):
  * `-report hotspots -format csv` without `-csv-delimiter` is empirically
    TAB-delimited (Intel documents no default); the delimiter is sniffed from
    the header line so comma output parses too.
  * `-report summary` text exists in a 4-column Top Hotspots variant (2025,
    with '% of CPU Time(%)') and a 3-column variant (2021, percent computed).
"""

from __future__ import annotations

import csv
import re

from ..core.models import HotspotRow

METRIC = "cpu_time_sec"

# CSV columns lifted into HotspotRow["extra"] when present (sw + hw sampling).
_EXTRA_COLS = {
    "CPU Time:Effective Time": "effective_time_sec",
    "CPU Time:Spin Time": "spin_time_sec",
    "CPU Time:Overhead Time": "overhead_time_sec",
    "Instructions Retired": "instructions_retired",
    "Microarchitecture Usage(%)": "microarchitecture_usage_pct",
    "Microarchitecture Usage:CPI Rate": "cpi_rate",
}

_TIME_RE = re.compile(r"^\d+(?:\.\d+)?s$")
# A summary metric value: a number plus an optional unit and/or trailing
# parenthetical, e.g. '16.663s', '16', '6.3% (2.755 out of 44)', '1.23x'.
_METRIC_VALUE_RE = re.compile(r"^(-?\d+(?:\.\d+)?)\s*(?:s|%|x|GHz)?(?:\s*\(.*\))?$")


def _to_float(raw: str) -> float | None:
    s = raw.strip().rstrip("sx%")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_hotspots_csv(text: str) -> list[HotspotRow]:
    """Parse `-report hotspots -format csv` output (tab- or comma-delimited)."""
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("vtune:")]
    if not lines:
        return []
    delimiter = "\t" if "\t" in lines[0] else ","
    parsed = list(csv.reader(lines, delimiter=delimiter))
    header = [h.strip() for h in parsed[0]]
    if "CPU Time" not in header:
        return []
    val_i = header.index("CPU Time")
    # Ungrouped reports lead with "Function"; a -group-by report leads with the
    # grouping column instead (e.g. "Module"). Use whichever key column exists so
    # grouped output parses rather than silently returning nothing.
    fn_i = header.index("Function") if "Function" in header else 0
    mod_i = header.index("Module") if "Module" in header else None
    extras = [(header.index(col), key) for col, key in _EXTRA_COLS.items() if col in header]

    prelim: list[tuple[str, str, float, dict[str, float]]] = []
    for row in parsed[1:]:
        if len(row) <= max(fn_i, val_i):
            continue
        function = row[fn_i].strip()
        value = _to_float(row[val_i])
        if not function or value is None:
            continue
        module = row[mod_i].strip() if mod_i is not None and len(row) > mod_i else ""
        extra: dict[str, float] = {}
        for idx, key in extras:
            if idx < len(row):
                v = _to_float(row[idx])
                if v is not None:
                    extra[key] = v
        prelim.append((function, module, value, extra))

    total = sum(v for _, _, v, _ in prelim)
    rows: list[HotspotRow] = []
    for function, module, value, extra in prelim:
        out: HotspotRow = {
            "function": function,
            "module": module,
            "metric": METRIC,
            "value": value,
            "percent": round(value / total * 100, 2) if total > 0 else 0.0,
        }
        if extra:
            out["extra"] = extra
        rows.append(out)
    return rows


def parse_summary_text(text: str) -> dict:
    """Parse `-report summary` text into a structured dict.

    Keys: elapsed_sec, cpu_time_sec, metrics, top_hotspots, platform_info,
    notes (the ' | '-prefixed issue blocks, one joined string per metric).
    """
    elapsed: float | None = None
    cpu_time: float | None = None
    metrics: dict[str, float] = {}
    top: list[HotspotRow] = []
    platform: dict[str, str] = {}
    notes: list[str] = []

    lines = text.splitlines()
    i = 0
    in_platform = False
    block_stack: list[tuple[int, str]] = []  # (indent, name) of platform sub-blocks, e.g. CPU
    note_buf: list[str] = []
    note_key = ""
    last_metric_key = ""

    def flush_notes() -> None:
        nonlocal note_buf, note_key
        if note_buf:
            body = " ".join(note_buf)
            notes.append(f"{note_key}: {body}" if note_key else body)
        note_buf = []
        note_key = ""

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if line.startswith("vtune:"):
            i += 1
            continue
        if stripped.startswith("|"):
            if not note_buf:
                note_key = last_metric_key
            note_buf.append(stripped.lstrip("|").strip())
            i += 1
            continue
        flush_notes()

        if not stripped:
            in_platform = False  # blank line ends the platform section (hint block follows)
            i += 1
            continue
        if stripped == "Top Hotspots":
            top, i = _parse_top_table(lines, i + 1)
            continue
        if stripped == "Collection and Platform Info":
            in_platform = True
            block_stack = []
            i += 1
            continue

        indent = len(line) - len(line.lstrip(" "))
        if in_platform and indent == 0:
            in_platform = False

        key, sep, value = stripped.partition(":")
        key = key.strip()
        value = value.strip()

        if in_platform:
            while block_stack and block_stack[-1][0] >= indent:
                block_stack.pop()
            if not sep:
                block_stack.append((indent, key))
            else:
                prefix = " ".join(name for _, name in block_stack)
                platform[f"{prefix} {key}" if prefix else key] = value
            i += 1
            continue

        if sep:
            m = _METRIC_VALUE_RE.match(value)
            if m:
                num = float(m.group(1))
                last_metric_key = key
                if key == "Elapsed Time" and elapsed is None:
                    elapsed = num
                elif key == "CPU Time" and cpu_time is None:
                    cpu_time = num
                else:
                    metrics[key] = num
        i += 1

    flush_notes()
    return {
        "elapsed_sec": elapsed,
        "cpu_time_sec": cpu_time,
        "metrics": metrics,
        "top_hotspots": top,
        "platform_info": platform,
        "notes": notes,
    }


def _parse_top_table(lines: list[str], i: int) -> tuple[list[HotspotRow], int]:
    """Parse the space-aligned Top Hotspots table; returns (rows, next line index).

    Column extents come from the dashes row, so both the 4-column (2025) and
    3-column (2021, no percent) variants slice correctly.
    """
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i + 1 >= len(lines):
        return [], i
    header, dashes = lines[i], lines[i + 1]
    if "-" not in dashes or not re.fullmatch(r"[-\s]+", dashes):
        return [], i
    extents = [(m.start(), m.end()) for m in re.finditer(r"-+", dashes)]
    names = [header[s:e].strip() for s, e in extents]

    def col(name: str) -> int | None:
        return names.index(name) if name in names else None

    fn_i, mod_i = col("Function"), col("Module")
    val_i, pct_i = col("CPU Time"), col("% of CPU Time(%)")
    if fn_i is None or val_i is None:
        return [], i

    def cell(line: str, ci: int) -> str:
        s, e = extents[ci]
        return line[s:e].strip()

    prelim: list[tuple[str, str, float, float | None]] = []
    i += 2
    while i < len(lines):
        line = lines[i]
        raw_val = cell(line, val_i)
        if not line.strip() or not _TIME_RE.match(raw_val):
            break
        pct: float | None = None
        if pct_i is not None:
            pct = _to_float(cell(line, pct_i))
        module = cell(line, mod_i) if mod_i is not None else ""
        prelim.append((cell(line, fn_i), module, float(raw_val[:-1]), pct))
        i += 1

    total = sum(v for _, _, v, _ in prelim)
    rows: list[HotspotRow] = []
    for function, module, value, pct in prelim:
        if pct is None:
            pct = round(value / total * 100, 2) if total > 0 else 0.0
        rows.append(
            {"function": function, "module": module, "metric": METRIC,
             "value": value, "percent": pct}
        )
    return rows, i


def parse_version_output(text: str) -> str:
    """Best-effort version string from `vtune -version` output."""
    stripped = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for s in stripped:
        if "vtune" in s.lower() and any(c.isdigit() for c in s):
            return s
    return stripped[0] if stripped else ""
