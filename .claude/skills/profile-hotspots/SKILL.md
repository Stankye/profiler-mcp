---
name: profile-hotspots
description: Profile a program's CPU hotspots with the vtune or uprof MCP server and interpret the results. Use when asked to find hotspots, profile a binary, or explain where CPU time goes.
---

# Profile hotspots

## Choosing a server

1. Call `vtune_check` and `uprof_check` first. They tell you which profiler is actually
   available, in which **mode** (`real`, `mock`, `unavailable`), and any platform caveats.
2. On Intel CPUs prefer vtune; on AMD CPUs prefer uprof (VTune's hw sampling and uProf's
   PMC/IBS configs each need their own vendor's silicon). On Intel, uProf only supports
   `tbp` (timer) collection. Either server in `mock` mode is fine for testing workflows —
   but **never present mock numbers as real measurements**; every result is stamped with
   its mode.

## Collecting

- `vtune_collect(analysis="hotspots", command=["/abs/path/app", "arg"], ...)` or
  `uprof_collect(config="hotspots", command=[...])`. Use absolute paths for the target.
- Attach to a running process with `pid=` instead of `command=` — then `duration_sec` is
  required.
- Keep first runs short and representative (workloads with a `--seconds N` style knob are
  ideal). Both tools return a `result_id` — everything downstream takes that id.
- If collection fails, the error text usually names the fix (missing binary, permissions:
  `perf_event_paranoid`, driver). Re-run `*_check` after changing the environment.

## Reading results

- Start with `*_report_summary(result_id)` — elapsed vs CPU time tells you the
  parallelism story before any function ranking.
- `*_report_hotspots(result_id, top_n=10)` gives normalized rows
  `{function, module, metric, value, percent}`. A healthy profile concentrates time in
  few functions; a flat profile (many ~2% rows) means the workload or inlining needs
  attention, not micro-optimization.
- Drill down only when needed via `vtune_report_raw` (other report types: `top-down`,
  `callstacks`, `hw-events`) or `uprof_report_raw` — output is byte-capped; narrow with
  filters instead of paging through everything.

## Interpreting

- >30% in one leaf function → optimize that function (algorithm first, then code).
- High CPU time in runtime libs (`libgomp`, `libpthread`) → synchronization/imbalance;
  switch to a threading-oriented analysis (`vtune_collect(analysis="threading")`).
- Memory-bound suspicion (high time, low IPC) → `analysis="memory-access"` (VTune, needs
  uncore access) or `config="memory"`/`"ibs"` (uProf, needs AMD hw).
- Record the `result_id` of any baseline you may want to compare against later; the
  optimize-loop skill builds on `*_compare`.
