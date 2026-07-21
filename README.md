# profiler-mcp

> [!CAUTION]
> **⚠️ NOT READY FOR USE — EXPERIMENTAL / UNVERIFIED-ON-HARDWARE. ⚠️**
>
> This project was built and tested **entirely in mock mode** on an Apple-Silicon Mac. It has
> **never been run against a real Intel VTune or AMD uProf install**, on any CPU. The mock
> backends are modeled on verbatim captures of real CLI output, but the real-hardware code paths
> (binary discovery, live collection, actual CSV/summary parsing on your version, permission and
> driver handling) are **unexercised and will likely need fixing**. The command-line flag surfaces
> are reconstructed from documentation and may not match your installed version. There is **no
> released version, no stability guarantee, and no support**. Treat this as a design prototype and
> a starting point to fork — **do not point it at production workloads or trust its numbers**, and
> read [Status & known limitations](#status--known-limitations) before doing anything with it.

Two MCP servers that put CPU profilers in front of coding agents: **vtune** (Intel VTune
Profiler, 7 tools) and **uprof** (AMD uProf, 9 tools) — one Python package, one shared core.
Neither profiler runs on macOS or on machines without the right silicon, so each server ships a
byte-realistic mock backend (derived from verbatim captures of the real CLIs) that lets the whole
project run, self-test, and even self-optimize anywhere.

```
MCP client (Claude Code)
    │ stdio (default) or streamable-http
    ▼
vtune-mcp / uprof-mcp      server.py  — FastMCP tool surface
    │                      cli.py     — argv construction
    ▼
core/runner.py subprocess ──► real `vtune` / `AMDuProfCLI`
    │                   └───► or mocks/*_mock.py   (picked by core/config.py; auto-mock iff no real binary)
    ▼
parse.py ──► TypedDicts (core/models.py) ──► core/store.py registry (result_id, e.g. "hs-0000")
                  core/compare.py ──► verdict ──► fail_on_regression gate for optimize loops
```

## Quickstart

```bash
uv sync                      # Python >=3.11; only runtime dep is the mcp SDK (pinned >=1.28,<2)
uv run pytest                # deterministic self-test gate (layers 1-4, see below)
make -C examples/workloads   # compile the deterministic example workload (hotspots)
```

Registering with Claude Code: the repo ships a project-scope [.mcp.json](.mcp.json) that starts
both servers with `uv run vtune-mcp` / `uv run uprof-mcp` — open Claude Code in this directory and
it works out of the box on any machine (mock mode auto-activates where the real profilers are
absent). To register explicitly instead:

```bash
claude mcp add vtune -- uv run vtune-mcp        # from inside this repo
claude mcp add uprof -- uv run uprof-mcp
# or from anywhere, at user scope:
claude mcp add --scope user vtune -- uv run --directory /path/to/profiler-mcp vtune-mcp
```

A typical conversation (mock mode shown; identical flow with `uprof_*`):

```
> what profiling is available here?
  vtune_check() -> mode: "mock", binary: .../mocks/vtune_mock.py, 15 analyses
> profile the example workload's compute phase
  vtune_collect(analysis="hotspots",
                command=["examples/workloads/hotspots", "--seconds", "5", "--only", "compute"])
  -> result_id: "hs-0000"
> where does the time go?
  vtune_report_hotspots(result_id="hs-0000") -> hot_compute 95%, main 5%
  (notes: "Mock mode: synthetic data — do not treat numbers as real hardware measurements.")
```

## Tool reference

### vtune (7 tools)

| Tool | Purpose | Key params |
|---|---|---|
| `vtune_check` | Probe env: binary, version, platform, active mode, available analyses | — |
| `vtune_collect` | Run a collection; stores the result, returns a `result_id` handle | `analysis`; `command` or `pid` (+`duration_sec`); `knobs`, `working_dir`, `data_limit_mb`, `label`, `allow_unknown` |
| `vtune_list_results` | List stored results: id, analysis, target, mode, created | — |
| `vtune_report_summary` | Parsed run overview: elapsed/CPU time, metrics, top hotspots | `result_id` |
| `vtune_report_hotspots` | Top-N hottest functions, CPU time descending | `result_id`, `top_n` (clamped to 100), `group_by`, `filters` |
| `vtune_report_raw` | Escape hatch: any vtune report type as byte-capped text | `result_id`, `report_type`, `extra_args`, `allow_unknown` |
| `vtune_compare` | Function-by-function baseline-vs-candidate deltas + pass/fail verdict | `baseline_id`, `candidate_id`, `threshold_pct`, `noise_floor_pct`, `fail_on_regression` |

### uprof (9 tools)

| Tool | Purpose | Key params |
|---|---|---|
| `uprof_check` | Probe env; notes that non-AMD CPUs support only `tbp` | — |
| `uprof_collect` | Run a collection; stores the session, returns a `result_id` handle | `config`; `command` or `pid` (+`duration_sec`); `call_graph`, `extra_events`, `working_dir`, `label`, `allow_unknown` |
| `uprof_list_results` | List stored results: id, config, target, mode, created | — |
| `uprof_report_summary` | Parsed run overview: duration, top hotspots, host details | `result_id` |
| `uprof_report_hotspots` | Top-N hottest functions, sample share descending | `result_id`, `top_n` (clamped to 100), `ignore_system_modules` |
| `uprof_report_raw` | Escape hatch: generated report CSV as byte-capped text | `result_id`, `extra_args` |
| `uprof_compare` | Function-by-function baseline-vs-candidate deltas + pass/fail verdict | `baseline_id`, `candidate_id`, `threshold_pct`, `noise_floor_pct`, `fail_on_regression` |
| `uprof_timechart` | Sample power/frequency/thermal counters; per-counter summaries | `events`, `duration_sec`, `interval_ms` (min 10), `command` |
| `uprof_system_info` | Parsed `AMDuProfCLI info --system`: CPU model, cores, OS | — |

Results persist server-side under short ids; tools return capped structured summaries, never raw
dumps. Every result is stamped with the `mode` it was collected in.

## Real hardware setup

**Linux x86 — VTune** (oneAPI Base Toolkit or standalone): `source
/opt/intel/oneapi/vtune/latest/env/vars.sh` puts `vtune` on PATH, or set `VTUNE_MCP_BIN` to the
binary; the conventional install paths are probed automatically. Driverless hardware sampling
needs `perf_event_paranoid <= 1` (`0` for system-wide/uncore, which `memory-access` requires) —
`vtune_check` warns when the setting blocks collection. Validate an install with
`<install-dir>/bin64/vtune-self-checker.sh`.

**Linux x86 — uProf**: installs land in `/opt/AMDuProf_X.Y-ZZZ/`; the newest
`/opt/AMDuProf_*/bin/AMDuProfCLI` is found automatically, or set `UPROF_MCP_BIN`. `timechart` and
the `energy` config additionally need the AMDPowerProfiler kernel driver (auto-installed by
rpm/deb; `sudo ./AMDPowerProfilerDriver.sh install` for tar installs). On Intel CPUs uProf runs
**`tbp` (timer-based) only** — PMC/IBS/energy configs need AMD hardware.

**Windows**: default install paths are probed (`C:\Program Files
(x86)\Intel\oneAPI\vtune\latest\bin64\vtune.exe`, `C:\Program
Files\AMD\AMDuProf\bin\AMDuProfCLI.exe`); the `*_MCP_BIN` overrides work the same way.

**macOS: mock mode only.** VTune dropped macOS support entirely in 2024.0 and uProf never had it,
so there is nothing real to run; `auto` mode falls back to the mocks.

## Mock mode

The mocks (`src/profiler_mcp/mocks/`) are not stubs. They are byte-realistic emulations of the
vendor CLIs, built from verbatim captured output (`docs/research/captures-*.md`), strict about
flags (unknown options are errors, so server argv bugs fail loudly), and they **actually execute
the profiled command** — process lifecycle, exit codes, working dirs, and timeouts are all real.
Sample attribution is synthetic and deterministic, driven by a `<binary>.mockprofile.json` sidecar
model next to the target (see `examples/workloads/hotspots.mockprofile.json`); a generic model
applies otherwise.

What they are **not**: measurements. The weights are fixed, so mock numbers do not respond to your
code edits — use mock mode to exercise tooling and workflows, real mode to optimize programs.
Every mock-collected result carries an explicit mock-data note.

Fault injection for testing error paths:

| Env | Effect |
|---|---|
| `MOCK_FAIL=collect-perm` | permission refusal (perf_event_paranoid-style, verbatim vendor text) |
| `MOCK_FAIL=collect-hang` | wedged collection that ignores duration (exercises timeouts) |
| `MOCK_FAIL=report-empty` | empty/truncated report output |
| `MOCK_FAIL=bad-exit` | nonzero exit after normal-looking output |
| `MOCK_FIXED_TIME=<unix-sec>` | freezes every emitted timestamp for byte-exact assertions |

## Self-testing and self-optimization

The full story is in [docs/SELF_TESTING.md](docs/SELF_TESTING.md). The pyramid:

| Layer | Where | Catches |
|---|---|---|
| 1 Unit | `tests/test_core_*`, parser tests | parser/logic regressions against verbatim fixtures |
| 2 In-memory MCP | `tests/test_vtune_*`, `tests/test_uprof_*` | tool wiring, schemas, error mapping (no subprocess) |
| 3 Stdio smoke | `tests/test_stdio_smoke.py` | entry points and transport, as a client runs them |
| 4 Ground-truth e2e | `tests/test_ground_truth.py` | compile → collect → report; attribution must match the sidecar model; seeded regression must fail `*_compare` |
| 5 Agentic | `.claude/workflows/self-test.js` | LLM-facing quality: probe agents drive both servers over real stdio; failures adversarially verified |

Layers 1–4 are the deterministic gate: `uv run pytest`. Layer 5 runs via the Workflow tool with
`{scriptPath: ".claude/workflows/self-test.js"}`; the companion
`{scriptPath: ".claude/workflows/optimize-project.js"}` is the test-gated self-improvement loop
(find → adversarial verify → apply one at a time → re-gate). Agent skills in `.claude/skills/`:
`profile-hotspots` (drive either server and interpret results), `optimize-loop` (verdict-gated
baseline/change/compare protocol), `profiler-selftest` (run and extend the pyramid).

## Configuration reference

| Var | Meaning | Default |
|---|---|---|
| `PROFILER_MCP_MODE` | `real` / `mock` / `auto` | `auto` — real binary when found, else mock |
| `VTUNE_MCP_BIN` | explicit vtune binary path | `vtune` on PATH, else conventional oneAPI paths |
| `UPROF_MCP_BIN` | explicit AMDuProfCLI path | `AMDuProfCLI` on PATH, else newest `/opt/AMDuProf_*/bin/AMDuProfCLI` |
| `PROFILER_MCP_RESULTS_DIR` | base dir for stored results + registry | `~/.profiler-mcp/<server>` |
| `PROFILER_MCP_MOCK_BIN` | explicit mock script to run instead of the in-package mocks | `src/profiler_mcp/mocks/<server>_mock.py` |
| `PROFILER_MCP_TIMEOUT_GRACE` | seconds added to a collection's duration for the subprocess timeout | `120` |

## Status & known limitations

This is a **prototype**, honest about what it is:

- **Never run on real hardware.** Everything here was developed and validated in mock mode. The
  `real` mode paths are best-effort and unverified. Expect to fix binary discovery, argument
  construction, and — most likely — the parsers, which are written against captured samples that
  may differ from your VTune/uProf version's actual output.
- **CLI surfaces are reconstructed** from vendor docs and public captures, not from a live tool.
  Both vendors change flags across versions (uProf 5.0 "simplified CLI options"; VTune knob names
  vary by release). `*_check` currently reports a **hardcoded** analysis/config list rather than
  querying the installed tool.
- **Auto-discovery of the uProf binary sorts install paths lexicographically**, so e.g.
  `AMDuProf_5.9` can win over `AMDuProf_5.10`. Set `UPROF_MCP_BIN` explicitly.
- **`real`-mode report tools re-run the CLI on every call** (results are only partially cached),
  and `*_report_raw`/`*_report_hotspots` carry a `readOnlyHint` even though the first call may
  generate a report file as a side effect.
- **uProf stdout parsing keys on marker lines** (`Generated data files path:` etc.); a profiled
  program that prints those same strings could in principle confuse session-dir discovery (a
  newest-directory glob is the fallback).
- **Concurrency is best-effort.** Result-id reservation is atomic (via directory creation) and
  registry writes take a POSIX file lock, but the lock degrades to a no-op on Windows.
- **The mock's numbers are fixed weights** — they do not respond to code changes, so the optimize
  loop exercises the *machinery*, not real speedups, in mock mode.

The code passes a 97-test deterministic suite plus an agentic self-test, and a five-lens
adversarial review whose nine confirmed findings were fixed and regression-tested — but all of
that is against the mocks. Contributions that exercise it on actual VTune/uProf installs are
exactly what it needs. See [docs/DESIGN.md](docs/DESIGN.md) for the architecture and rationale.

## License

MIT ([LICENSE](LICENSE)). The uProf invocation and stdout-contract knowledge derives from
AMDResearch/intellikit (MIT, AMD) — re-implemented, not vendored; see [NOTICE](NOTICE).

**No warranty.** Provided as-is under the MIT license; see the caution at the top.
