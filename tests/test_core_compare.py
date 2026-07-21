"""Layer 1: compare_hotspots — classifications, noise floor, and the verdict gates."""

from __future__ import annotations

from profiler_mcp.core.compare import compare_hotspots
from profiler_mcp.core.models import HotspotRow


def row(function: str, value: float, percent: float, module: str = "app") -> HotspotRow:
    return {
        "function": function,
        "module": module,
        "metric": "cpu_time_sec",
        "value": value,
        "percent": percent,
    }


def by_function(rows) -> dict:
    return {r["function"]: r for r in rows}


def test_identical_rows_pass() -> None:
    base = [
        row("hot_compute", 10.0, 50.0),
        row("hot_memory", 6.0, 30.0),
        row("hot_branch", 4.0, 20.0),
    ]
    rows, verdict, total_base, total_cand, total_delta = compare_hotspots(base, list(base))
    assert verdict["passed"] is True
    assert verdict["worst_regression_pct"] == 0.0
    assert verdict["threshold_pct"] == 5.0
    assert total_base == total_cand == 20.0
    assert total_delta == 0.0
    assert {r["classification"] for r in rows} == {"unchanged"}
    # Rows come back sorted by the larger run's value, descending.
    assert [r["function"] for r in rows] == ["hot_compute", "hot_memory", "hot_branch"]


def test_seeded_single_function_regression_fails_and_names_function() -> None:
    # hot_leaf +50% while the total stays under threshold: the FUNCTION gate fires.
    base = [row("big_stable", 100.0, 90.9), row("hot_leaf", 10.0, 9.1)]
    cand = [row("big_stable", 100.0, 87.0), row("hot_leaf", 15.0, 13.0)]
    rows, verdict, _tb, _tc, total_delta = compare_hotspots(base, cand)
    assert total_delta < 5.0  # total gate must NOT be the trigger here
    assert verdict["passed"] is False
    assert "hot_leaf" in verdict["reason"]
    assert verdict["worst_regression_pct"] == 50.0
    leaf = by_function(rows)["hot_leaf"]
    assert leaf["classification"] == "regression"
    assert leaf["delta"] == 5.0
    assert leaf["delta_pct"] == 50.0


def test_improvement_classification_passes() -> None:
    base = [row("big_stable", 100.0, 87.0), row("hot_leaf", 15.0, 13.0)]
    cand = [row("big_stable", 100.0, 93.0), row("hot_leaf", 7.5, 7.0)]
    rows, verdict, *_ = compare_hotspots(base, cand)
    assert verdict["passed"] is True
    leaf = by_function(rows)["hot_leaf"]
    assert leaf["classification"] == "improvement"
    assert leaf["delta_pct"] == -50.0


def test_removed_function_never_fails_the_verdict() -> None:
    base = [row("main", 100.0, 90.9), row("gone", 10.0, 9.1)]
    cand = [row("main", 100.0, 100.0)]
    rows, verdict, *_ = compare_hotspots(base, cand)
    gone = by_function(rows)["gone"]
    assert gone["classification"] == "removed"
    assert gone["candidate_value"] == 0.0
    assert verdict["passed"] is True  # removals are improvements, not regressions


def test_added_function_with_flat_total_passes() -> None:
    # A new symbol offset by an existing one shrinking (rename/refactor; total flat)
    # must NOT fail: an "added" function is a +100% change from zero, but treating any
    # new symbol as a regression spuriously fails renames and inlining changes.
    base = [row("main", 100.0, 100.0)]
    cand = [row("main", 96.0, 96.0), row("newfn", 4.0, 4.0)]
    rows, verdict, *_ = compare_hotspots(base, cand)
    new = by_function(rows)["newfn"]
    assert new["classification"] == "added"
    assert new["candidate_value"] == 4.0
    assert new["delta_pct"] == 100.0  # zero-baseline convention, still reported per-row
    assert verdict["passed"] is True


def test_empty_candidate_against_real_baseline_fails() -> None:
    # A candidate with no functions (failed/empty run) is not a valid comparison —
    # it must fail loudly rather than report "everything removed / improved".
    base = [row("main", 100.0, 100.0)]
    _rows, verdict, _tb, _tc, _delta = compare_hotspots(base, [])
    assert verdict["passed"] is False
    assert "no functions" in verdict["reason"].lower() or "empty" in verdict["reason"].lower()


def test_new_hot_function_raising_total_fails_via_total_gate() -> None:
    # A genuinely new function that ADDS work (total 100 -> 130) is caught by the
    # total gate, with a correct reason, rather than a bogus per-function "+100%".
    base = [row("main", 100.0, 100.0)]
    cand = [row("main", 100.0, 76.9), row("newfn", 30.0, 23.1)]
    _rows, verdict, _tb, _tc, total_delta = compare_hotspots(base, cand)
    assert verdict["passed"] is False
    assert total_delta > 5.0
    assert "Total" in verdict["reason"]


def test_noise_floor_exempts_tiny_function() -> None:
    # `tiny` doubles, but its share is below the 1% floor in BOTH runs.
    base = [row("main", 100.0, 99.5), row("tiny", 0.5, 0.5)]
    cand = [row("main", 100.0, 99.0), row("tiny", 1.0, 0.99)]
    rows, verdict, *_ = compare_hotspots(base, cand)
    tiny = by_function(rows)["tiny"]
    assert tiny["classification"] == "regression"  # still listed and classified
    assert verdict["passed"] is True  # ...but exempt from the verdict

    # Same data with the floor lowered: now it counts and fails.
    _, strict_verdict, *_ = compare_hotspots(base, cand, noise_floor_pct=0.1)
    assert strict_verdict["passed"] is False
    assert "tiny" in strict_verdict["reason"]


def test_total_regression_gate() -> None:
    # The only function is below the noise floor (exempt from the function gate),
    # yet the TOTAL doubles: the total gate must still fail the comparison.
    base = [row("dust", 10.0, 0.5)]
    cand = [row("dust", 20.0, 0.5)]
    _rows, verdict, total_base, total_cand, total_delta = compare_hotspots(base, cand)
    assert (total_base, total_cand, total_delta) == (10.0, 20.0, 100.0)
    assert verdict["passed"] is False
    assert verdict["reason"].startswith("Total metric regressed")
    assert verdict["worst_regression_pct"] == 100.0


def test_threshold_pct_is_respected() -> None:
    base = [row("f", 10.0, 100.0)]
    cand = [row("f", 11.0, 100.0)]  # +10%
    rows, loose, *_ = compare_hotspots(base, cand, threshold_pct=15.0)
    assert loose["passed"] is True
    assert by_function(rows)["f"]["classification"] == "unchanged"  # within threshold
    _, strict, *_ = compare_hotspots(base, cand, threshold_pct=5.0)
    assert strict["passed"] is False
    assert strict["threshold_pct"] == 5.0
