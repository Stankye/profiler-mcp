"""Output capping for raw/escape-hatch tool results.

Raw profiler reports can be arbitrarily large; Claude Code truncates tool
responses around 25k tokens, and blowing the context is worse than losing the
middle of a report. Cap with head+tail so both the column headers and the
totals/footers survive.
"""

from __future__ import annotations

DEFAULT_CAP_BYTES = 32_000  # ~8k tokens, well under client truncation limits


def cap_text(text: str, cap_bytes: int = DEFAULT_CAP_BYTES) -> tuple[str, bool]:
    """Return (possibly capped text, was_truncated)."""
    data = text.encode("utf-8", errors="replace")
    if len(data) <= cap_bytes:
        return text, False
    head = data[: cap_bytes * 2 // 3].decode("utf-8", errors="replace")
    tail = data[-cap_bytes // 3 :].decode("utf-8", errors="replace")
    marker = (
        f"\n\n[... TRUNCATED {len(data) - cap_bytes:,} bytes — "
        "narrow with top_n / filters, or read the file from the result_dir ...]\n\n"
    )
    return head + marker + tail, True


def clamp_top_n(top_n: int, *, default: int = 10, maximum: int = 100) -> int:
    if top_n <= 0:
        return default
    return min(top_n, maximum)
