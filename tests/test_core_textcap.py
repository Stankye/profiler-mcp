"""Layer 1: textcap — byte capping with head+tail structure, top_n clamping."""

from __future__ import annotations

from profiler_mcp.core.textcap import DEFAULT_CAP_BYTES, cap_text, clamp_top_n

CAP = 300  # small explicit cap keeps the structural assertions readable


def _sample(n: int) -> str:
    return "".join(str(i % 10) for i in range(n))


def test_under_cap_returned_unchanged() -> None:
    text = _sample(CAP - 1)
    assert cap_text(text, CAP) == (text, False)


def test_exactly_at_cap_not_truncated() -> None:
    text = _sample(CAP)
    assert cap_text(text, CAP) == (text, False)


def test_one_over_cap_truncates_with_head_tail_and_marker() -> None:
    text = _sample(CAP + 1)
    capped, truncated = cap_text(text, CAP)
    assert truncated is True
    head = text[: CAP * 2 // 3]
    tail = text[-(CAP // 3) :]
    assert capped.startswith(head)
    assert capped.endswith(tail)
    marker = capped[len(head) : -len(tail)]
    assert "TRUNCATED" in marker
    assert "1 bytes" in marker  # reports exactly how much was dropped
    assert capped == head + marker + tail  # nothing else — pure head+marker+tail


def test_large_input_marker_reports_dropped_bytes() -> None:
    text = _sample(10 * CAP)
    capped, truncated = cap_text(text, CAP)
    assert truncated is True
    dropped = len(text) - CAP
    assert f"{dropped:,}" in capped
    assert len(capped) < len(text)


def test_multibyte_input_does_not_crash_at_boundaries() -> None:
    text = "é" * CAP  # 2 bytes each: cap cuts through a code point
    capped, truncated = cap_text(text, CAP)
    assert truncated is True
    assert "TRUNCATED" in capped


def test_default_cap_is_used_when_unspecified() -> None:
    text = _sample(DEFAULT_CAP_BYTES * 2)
    capped, truncated = cap_text(text)
    assert truncated is True
    # Head (2/3) + tail (1/3) + marker: near the cap, far below the input size.
    assert DEFAULT_CAP_BYTES <= len(capped.encode()) < DEFAULT_CAP_BYTES + 200
    assert cap_text(_sample(DEFAULT_CAP_BYTES))[1] is False


def test_clamp_top_n_defaults_and_max() -> None:
    assert clamp_top_n(0) == 10  # non-positive -> default
    assert clamp_top_n(-3) == 10
    assert clamp_top_n(1) == 1
    assert clamp_top_n(7) == 7
    assert clamp_top_n(100) == 100
    assert clamp_top_n(101) == 100  # clamped to max
    assert clamp_top_n(10**9) == 100


def test_clamp_top_n_custom_default_and_max() -> None:
    assert clamp_top_n(0, default=5, maximum=20) == 5
    assert clamp_top_n(999, default=5, maximum=20) == 20
    assert clamp_top_n(3, default=5, maximum=20) == 3
