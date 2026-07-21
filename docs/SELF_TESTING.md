# Self-testing

The central constraint: **neither profiler runs here.** VTune dropped macOS entirely
(2024.0); uProf never supported it; both need x86 Linux/Windows for anything real. So the
project treats "no profiler hardware" as the default case, not the degenerate one — every
layer below runs anywhere, and the same layers run against the real CLIs unchanged on a
real Linux box (set `PROFILER_MCP_MODE=real`).

## Why mocks are trustworthy

The mocks aren't stubs — they are byte-realistic emulations built from **verbatim
captured output of the real tools** (`docs/research/captures-vtune.md`,
`captures-uprof.md`: real 2025-era transcripts, a complete byte-verified uProf
`report.csv`, empirically confirmed details like VTune's undocumented TAB default CSV
delimiter and uProf's trailing-space `Profiling (data collection) completed ` line).
Third-party parsers in the wild (intellikit's regexes, the wanggan768q server's tab
splitting) are part of the contract: our mock output satisfies them too.

Two rules keep this honest:

1. **Fixtures are vendor ground truth.** `tests/fixtures/*` hold verbatim captures. A
   parser change may never edit a fixture to pass; fixtures change only when new verbatim
   captures land in `docs/research/`.
2. **Mocks run the real target.** `*_collect` on the mock actually executes the profiled
   command — process lifecycle, exit codes, working dirs, and timeouts are all real. Only
   the *sample attribution* is synthetic, driven by the deterministic
   `<binary>.mockprofile.json` sidecar model.

## The pyramid

| Layer | Command | What breaks it |
|---|---|---|
| 1. Unit | `uv run pytest tests/test_core_* tests/test_*_parse*` | parser/logic regressions against verbatim fixtures |
| 2. In-memory MCP | `uv run pytest tests/test_vtune_* tests/test_uprof_*` | tool wiring, schemas, error mapping — via `create_connected_server_and_client_session`, no subprocess |
| 3. Stdio smoke | `uv run pytest tests/test_stdio_smoke.py` | entry points, transport, the actual `uv run vtune-mcp` a client executes |
| 4. Ground truth e2e | `uv run pytest tests/test_ground_truth.py` | the full chain: compile `hotspots.c` → collect via mock → report → parsed attribution must match the sidecar (`--only compute` ⇒ `hot_compute` ≥ 85%); a seeded slowdown must fail `*_compare`, an identical pair must pass |
| 5. Agentic | Workflow tool: `.claude/workflows/self-test.js` | LLM-facing quality: probe agents drive both servers over real stdio MCP (happy, error, fault-injected, token-size audits); every failure is adversarially re-verified before being reported |

Layers 1–4 are the deterministic gate (`uv run pytest`) — cheap, run constantly.
Layer 5 is judgment — run after meaningful changes.

## Fault injection

The mocks expose `MOCK_FAIL` so error paths are first-class tested behavior:

| Value | Simulates |
|---|---|
| `collect-perm` | real permission failures (perf_event_paranoid / missing sampling driver), verbatim vendor error text |
| `collect-hang` | a wedged collection — exercises server timeouts |
| `report-empty` | truncated/empty report files |
| `bad-exit` | nonzero exit after normal-looking output |

`MOCK_FIXED_TIME=<unix-sec>` freezes every timestamp the mocks emit, for byte-exact
assertions.

## The self-optimization loop

Because layer 5 produces *verified* findings, the project can improve itself safely:
`.claude/workflows/optimize-project.js` runs the self-test, mines improvement proposals
across five dimensions (ergonomics, mock fidelity, simplification, coverage, docs),
adversarially judges each, applies survivors one at a time with the full suite re-run
between applications, and reverts anything that breaks the gate. The deterministic
pyramid is what makes the agentic loop safe; the agentic loop is what finds the problems
the pyramid can't see.

## On real hardware (untested — aspirational)

This has **not been run on real hardware yet** (see the README caution). The intended
design: on an x86 Linux machine with the profilers installed,
`PROFILER_MCP_MODE=real uv run pytest tests/test_ground_truth.py` would profile the
workload with the actual vendor tools, with the sidecar model as a loose
expected-attribution oracle (tolerances must widen — real samplers are noisy). Expect the
parsers and binary/flag handling to need real fixes the first time it meets an actual
install; that is the top open work item.
