"""Baseline-vs-candidate hotspot comparison with a machine-checkable verdict.

The verdict is the contract that makes agentic optimize loops terminate: an
agent profiles, edits code, re-profiles, compares — and gets an unambiguous
pass/fail instead of eyeballing numbers. Time-like metrics are assumed
(bigger = worse).
"""

from __future__ import annotations

from .models import CompareRow, HotspotRow, RegressionVerdict


def compare_hotspots(
    baseline: list[HotspotRow],
    candidate: list[HotspotRow],
    *,
    threshold_pct: float = 5.0,
    noise_floor_pct: float = 1.0,
) -> tuple[list[CompareRow], RegressionVerdict, float, float, float]:
    """Compare two hotspot row sets keyed by (function, module).

    Returns (rows, verdict, total_baseline, total_candidate, total_delta_pct).
    Functions whose share is below `noise_floor_pct` in BOTH runs are ignored
    for the verdict (still listed) so sampling noise can't fail a comparison.
    """
    base_map = {(r["function"], r["module"]): r for r in baseline}
    cand_map = {(r["function"], r["module"]): r for r in candidate}

    total_base = sum(r["value"] for r in baseline)
    total_cand = sum(r["value"] for r in candidate)
    total_delta_pct = _pct_change(total_base, total_cand)

    rows: list[CompareRow] = []
    worst_regression = 0.0
    worst_name = ""

    for key in sorted(set(base_map) | set(cand_map), key=lambda k: -(
        base_map.get(k, cand_map.get(k))["value"]  # type: ignore[index]
    )):
        b = base_map.get(key)
        c = cand_map.get(key)
        b_val = b["value"] if b else 0.0
        c_val = c["value"] if c else 0.0
        delta = c_val - b_val
        delta_pct = _pct_change(b_val, c_val)

        significant = (
            (b is not None and b["percent"] >= noise_floor_pct)
            or (c is not None and c["percent"] >= noise_floor_pct)
        )
        if b is None:
            classification = "added"
        elif c is None:
            classification = "removed"
        elif abs(delta_pct) <= threshold_pct:
            classification = "unchanged"
        elif delta > 0:
            classification = "regression"
        else:
            classification = "improvement"

        # Only functions present in BOTH runs count toward the per-function
        # regression gate. An "added" function is a +100% change from zero, but a
        # rename (add X_v2, remove X) leaves the total flat — the total gate below
        # catches a genuinely new hot function via its effect on the total, without
        # spuriously failing renames/inlining changes.
        counts = significant and classification == "regression"
        if counts and delta_pct > worst_regression:
            worst_regression = delta_pct
            worst_name = key[0]

        rows.append(
            CompareRow(
                function=key[0],
                module=key[1],
                baseline_value=round(b_val, 6),
                candidate_value=round(c_val, 6),
                delta=round(delta, 6),
                delta_pct=round(delta_pct, 2),
                classification=classification,  # type: ignore[typeddict-item]
            )
        )

    # An empty candidate against a non-empty baseline is not a valid comparison —
    # the candidate run almost certainly failed or collected no samples. Fail
    # loudly instead of reporting a spurious "everything improved / removed".
    empty_candidate = bool(baseline) and not candidate
    total_regressed = total_delta_pct > threshold_pct
    func_regressed = worst_regression > threshold_pct
    passed = not (total_regressed or func_regressed or empty_candidate)
    if empty_candidate:
        reason = (
            "Candidate profile has no functions — the candidate run likely failed or "
            "collected no samples. Not a valid comparison; re-collect the candidate."
        )
    elif passed:
        reason = (
            f"Total {_fmt(total_delta_pct)} and no significant function regressed "
            f"more than {threshold_pct:.1f}%."
        )
    elif total_regressed:
        reason = f"Total metric regressed {_fmt(total_delta_pct)} (threshold {threshold_pct:.1f}%)."
    else:
        reason = (
            f"Function {worst_name!r} regressed {_fmt(worst_regression)} "
            f"(threshold {threshold_pct:.1f}%)."
        )

    verdict = RegressionVerdict(
        passed=passed,
        threshold_pct=threshold_pct,
        worst_regression_pct=round(max(worst_regression, total_delta_pct), 2),
        reason=reason,
    )
    return rows, verdict, round(total_base, 6), round(total_cand, 6), round(total_delta_pct, 2)


def _pct_change(base: float, cand: float) -> float:
    if base <= 0:
        return 100.0 if cand > 0 else 0.0
    return (cand - base) / base * 100.0


def _fmt(pct: float) -> str:
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"
