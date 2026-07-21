---
name: optimize-loop
description: Run an evidence-gated optimization loop on a program using the profiler MCP servers — baseline, change, re-profile, compare, keep or revert. Use when asked to "make it faster", optimize a hotspot, or validate a performance change.
---

# Optimize loop

The loop that turns a profiler into an optimizer. The compare tool's verdict is the
gate: no change is kept on vibes.

## Protocol

1. **Baseline.** Collect with fixed, repeatable workload parameters
   (`command=[app, "--seconds", "5"]` style; same machine, same load). Save the
   `result_id` — say it out loud in your response so it survives context loss.
   Run `*_report_hotspots` and pick ONE target: the top function you can actually change.
2. **Hypothesize before editing.** From the hotspot's signature (high `percent` +
   `extra` metrics like CPI/cache-miss where present) state what class of fix applies:
   algorithm, memory layout, branch shape, parallelism. One hypothesis, one change.
3. **Change.** Smallest edit that tests the hypothesis. Rebuild with identical flags.
4. **Verify correctness first.** Run the program's own tests/output check. A fast wrong
   program is a failure — never skip this step.
5. **Re-profile** with the exact same collection parameters → new `result_id`.
6. **Compare.** `*_compare(baseline_id, candidate_id, threshold_pct=5, fail_on_regression=true)`.
   - Tool errors with the verdict reason → the change regressed: **revert**, return to 2
     with the next hypothesis.
   - `verdict.passed` and total improved → keep the change; the candidate becomes the new
     baseline id.
   - `passed` but total within threshold → treat as neutral; keep only if it also
     improves clarity, else revert.
7. Repeat until the target function is off the top of the profile, the improvement goal
   is met, or two consecutive hypotheses fail (then stop and report honestly).

## Rules

- Never compare results from different modes (`real` vs `mock`) or different machines —
  the tools note mode mismatches; treat them as invalid comparisons.
- Sampling noise is real: below ~5% delta on short runs, lengthen the workload before
  believing a win.
- Keep a running table in your response: hypothesis → delta% → kept/reverted. That table
  is the deliverable, alongside the final diff.
- In mock mode this loop exercises the *machinery* (the mock's numbers won't respond to
  your code edits — weights are fixed). Use mock mode to test the loop itself, real mode
  to optimize actual programs.
