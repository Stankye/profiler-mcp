# profiler-mcp — Design

Two MCP servers — **vtune** (Intel VTune Profiler) and **uprof** (AMD uProf) — sharing one
Python package, one core library, and one self-testing story. Built so the entire project is
testable and optimizable on machines that cannot run either profiler (e.g. Apple Silicon macOS),
via high-fidelity **mock CLI binaries**.

## Evidence-based decisions

| Decision | Rationale (from research phase) |
|---|---|
| Official `mcp` SDK v1.x, pinned `mcp>=1.28,<2` | v2 (FastMCP→MCPServer rename) ships days from now; v1 is stable, has in-memory test support (`mcp.shared.memory.create_connected_server_and_client_session` accepts `FastMCP` directly). Not the third-party `fastmcp` package intellikit uses. |
| Always pass explicit result dirs (`-r` / `--output-dir`) | VTune silently picks the highest-numbered result in CWD when `-r` is omitted; uProf invents timestamped session dirs. Automation must never depend on CWD state or stdout parsing alone. |
| Parse uProf collect stdout for `Generated data files path:` / `Generated report file:` but fall back to newest-dir glob | Exact strings verified in intellikit source (MIT). Session dir names embed a timestamp (`AMDuProf-<APP>-<CONFIG>_<Mon-DD-YYYY_hh-mm-ss>`), so stdout is the primary channel, glob the fallback. |
| Summarize server-side; never return raw profile dumps | Every surveyed profiler MCP that works well (nsys, perfetto, XcodeTrace) persists results server-side and returns capped, structured summaries plus a handle (`result_id`). Claude Code truncates tool responses at 25k tokens; we cap far below that. |
| First-class `*_compare` tool with machine-checkable verdict | XcodeTraceMCP's `failOnRegression` pattern + PRAGMA paper: a hard pass/fail signal is what turns a profiler wrapper into an agentic optimize loop. |
| Escape-hatch raw-report tools, byte-capped | perfetto-mcp's curated-tools-plus-`execute_sql_query` design; ours is `*_report_raw` with head/tail truncation. |
| Mock CLIs actually execute the target program | Self-tests then validate real process lifecycle (env, cwd, exit codes, timeouts), not just parsing. Attribution comes from a deterministic per-binary profile model. |
| Exit codes: treat 0 = success, anything else = failure; capture stderr | Neither vendor documents numeric exit codes. |

## Repository layout

```
pyproject.toml               # package "profiler-mcp"; entry points: vtune-mcp, uprof-mcp
.mcp.json                    # project-scope registration of both servers
CLAUDE.md                    # project conventions + how to self-test
src/profiler_mcp/
  __init__.py
  core/
    models.py                # ALL shared TypedDicts/dataclasses (MCP structured-output types)
    config.py                # binary resolution, mock mode, results base dir (env-driven)
    runner.py                # subprocess execution: timeouts, env, CommandResult, error mapping
    store.py                 # SessionStore: result_id -> dir/meta registry, JSON-persisted
    textcap.py               # byte/row capping helpers for raw outputs
    compare.py               # generic hotspot-delta comparison + RegressionVerdict
  vtune/
    cli.py                   # vtune command construction (collect/report/version)
    parse.py                 # hotspots CSV + summary text parsers
    server.py                # FastMCP server "vtune"; console entry vtune-mcp
  uprof/
    cli.py                   # AMDuProfCLI command construction (profile/collect/report/timechart/info)
    parse.py                 # report.csv section parser, timechart CSV parser
    server.py                # FastMCP server "uprof"; console entry uprof-mcp
  mocks/                     # in-package so auto-mock works for installed copies too
    vtune_mock.py            # mock of the vtune CLI (invoked as `python vtune_mock.py ...`)
    uprof_mock.py            # mock of AMDuProfCLI
    # (each mock is deliberately self-contained stdlib-only; synthesis logic is
    #  duplicated rather than shared so either script runs standalone)
tests/
  fixtures/                  # verbatim-shaped report fragments captured from research
  conftest.py                # anyio backend, tmp results dir, compiled workload fixture
  test_core_*.py             # runner/store/compare/textcap unit tests
  test_vtune_*.py            # in-memory MCP tests against mock vtune
  test_uprof_*.py            # in-memory MCP tests against mock AMDuProfCLI
  test_stdio_smoke.py        # real stdio transport handshake + one tool call per server
  test_ground_truth.py       # e2e: compiled hotspots workload; attribution must match sidecar
examples/workloads/
  hotspots.c                 # deterministic workload: hot_compute/hot_memory/hot_branch
  hotspots.mockprofile.json  # sidecar profile model consumed by the mocks
  Makefile
.claude/skills/
  profile-hotspots/SKILL.md  # drive either server to find + interpret hotspots
  optimize-loop/SKILL.md     # baseline -> patch -> re-profile -> compare loop, verdict-gated
  profiler-selftest/SKILL.md # run/extend the self-test pyramid
.claude/workflows/
  self-test.js               # Workflow script: full test pyramid + adversarial verify of failures
  optimize-project.js        # find->verify->apply improvement loop over this repo itself
docs/
  DESIGN.md                  # this file
  SELF_TESTING.md            # the self-testing story, layer by layer
  research/                  # frozen research notes (CLI references, output captures)
```

## Configuration (env)

| Var | Meaning | Default |
|---|---|---|
| `VTUNE_MCP_BIN` | vtune binary | `vtune` on PATH, else `/opt/intel/oneapi/vtune/latest/bin64/vtune` |
| `UPROF_MCP_BIN` | AMDuProfCLI binary | `AMDuProfCLI` on PATH, else newest `/opt/AMDuProf_*/bin/AMDuProfCLI` |
| `PROFILER_MCP_RESULTS_DIR` | base dir for result dirs + registry | `~/.profiler-mcp/<server>` |
| `PROFILER_MCP_MODE` | `real` / `mock` / `auto` | `auto` (mock iff real binary absent) |
| `PROFILER_MCP_MOCK_BIN` | explicit mock script override (rarely needed) | in-package `profiler_mcp/mocks/<server>_mock.py` |
| `PROFILER_MCP_TIMEOUT_GRACE` | seconds added to collection duration for subprocess timeout | `120` |

`*_check()` tools report which mode is active; every collect result records it, and mock-mode
results are stamped `"mode": "mock"` so agents can never mistake synthetic numbers for real ones.

## Tool surface

Shared verb grammar across both servers (namespaced per Anthropic tool-design guidance):

| vtune server | uprof server | Notes |
|---|---|---|
| `vtune_check` | `uprof_check` | read-only env probe: binary, version, platform, perf_event_paranoid, active mode |
| `vtune_collect` | `uprof_collect` | launch/attach + collect; explicit result dir; returns `CollectResult` with `result_id` |
| `vtune_list_results` | `uprof_list_results` | registry of stored results (read-only) |
| `vtune_report_summary` | `uprof_report_summary` | parsed, capped run overview |
| `vtune_report_hotspots` | `uprof_report_hotspots` | structured top-N functions (`top_n` default 10, max 100) |
| `vtune_report_raw` | `uprof_report_raw` | escape hatch: any report type/args, byte-capped text |
| `vtune_compare` | `uprof_compare` | baseline vs candidate deltas + `RegressionVerdict`; `fail_on_regression` raises ToolError |
| — | `uprof_timechart` | power/frequency/thermal sampling summary (AMD hw only; mock supported) |
| — | `uprof_system_info` | `info --system` parsed |

Analysis types/configs are passed through as strings validated against a known list but
overridable (`allow_unknown=True`) because both vendors' lists are version/platform dependent.
`*_check` currently reports that **hardcoded** list; querying the installed tool for its live
capabilities (`vtune -help collect`, `AMDuProfCLI info --list collect-configs`) is a TODO — see
the known-limitations note in the README.

Collection targets: exactly one of `command` (argv list, run under the profiler) or `pid`
(attach; requires `duration_sec`). Both take `working_dir`, `duration_sec`, `label`;
vtune adds `knobs`/`data_limit_mb`, uprof adds `call_graph`/`extra_events`.

## Mock CLI design

Mocks are self-contained Python scripts (stdlib only, `#!/usr/bin/env python3`) that:

1. Parse the same flag surface the servers emit (strict: unknown flags → error exit, so server
   regressions in command construction fail loudly).
2. Actually run the target command (or sleep `duration` when attaching/system-wide), capturing
   its exit code and wall time.
3. Synthesize deterministic sample data: if `<target>.mockprofile.json` exists next to the
   target binary it defines function weights per phase (optionally keyed by target argv, e.g.
   `--only compute`); otherwise a generic model is used. Weights × measured wall time × nominal
   sample rate → sample counts. No randomness anywhere.
4. Write result artifacts in the vendor's shape (VTune: `r<NNN>hs`-style dir with marker files;
   uProf: timestamped `AMDuProf-<APP>-<CONFIG>_<ts>` session dir + `report.csv`) and emit
   byte-realistic stdout (uProf mock prints the two `Generated …` lines intellikit regexes on;
   report shapes follow `tests/fixtures/`, which follow verbatim captures in `docs/research/`).
5. Support fault injection via env (`MOCK_FAIL=<point>`): binary-missing is trivially testable,
   plus `collect-perm` (perf_event_paranoid-style refusal), `collect-hang` (ignores duration,
   for timeout tests), `report-empty`, `bad-exit`. Tests use these to exercise every error path.

## Self-testing pyramid (docs/SELF_TESTING.md expands)

1. **Unit** — parsers against fixtures; command construction golden tests; store round-trips.
2. **In-memory MCP** — `create_connected_server_and_client_session` per server, mocks active:
   every tool called through the real MCP layer, structured content asserted.
3. **Stdio smoke** — servers spawned as subprocesses; initialize handshake + `*_check` + one
   collect/report round-trip over the wire.
4. **Ground truth e2e** — compile `hotspots.c`, profile via mock, assert attribution matches the
   sidecar model (e.g. `--only compute` ⇒ `hot_compute` ≥ 85% of samples) and that
   `*_compare` flags a seeded regression and passes a no-change pair.
5. **Agentic self-test** — `.claude/workflows/self-test.js` runs layers 1–4, then fans out
   agents that exercise the servers *as MCP clients* the way a model would, and adversarially
   verifies any failure before reporting it.

Layer 5 is what makes the project self-optimizing: `optimize-project.js` runs the self-test,
mines transcripts/timings for friction (confusing tool errors, oversized outputs, slow paths),
proposes changes, verifies them against layers 1–4, and applies the survivors.

## Licensing

MIT. The uProf invocation/stdout-contract knowledge derives from AMDResearch/intellikit
(MIT, © 2025-2026 Advanced Micro Devices, Inc.); we re-implement rather than vendor code, with
attribution in NOTICE.
