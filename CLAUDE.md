# profiler-mcp

Two MCP servers — `vtune` (Intel VTune) and `uprof` (AMD uProf) — one package, one core,
fully self-testable without profiler hardware via byte-realistic mock CLIs.

## Commands

```bash
uv sync                      # deps (Python >=3.11, mcp SDK v1.x pinned <2)
uv run pytest                # deterministic gate: ALL of layers 1-4. Keep green.
uv run ruff check src tests
make -C examples/workloads   # compile the profiling workload (needed by e2e tests)
uv run vtune-mcp             # run a server on stdio (uprof-mcp likewise)
```

## Load-bearing invariants

- `tests/fixtures/*` are **verbatim vendor output** (provenance: `docs/research/captures-*.md`).
  Never edit them to make code pass — fix the code. New fixtures require new verbatim
  captures in `docs/research/` first.
- Mock CLIs (`src/profiler_mcp/mocks/`) are strict: unknown flags are errors, so server
  command-construction bugs surface as test failures. If you add a flag in
  `vtune/cli.py`/`uprof/cli.py`, teach the mock the same flag in the same change.
- All tool return shapes live in `core/models.py` (TypedDicts = wire contract). Change
  shapes there only, and expect both servers plus tests to move together.
- Every result is stamped with its `mode` (`real`/`mock`); anything user-visible that
  reports numbers must carry the mock caveat. Never let synthetic numbers pass as real.
- The two servers stay structurally parallel: a capability added to one gets added to the
  other (or the asymmetry documented, like `uprof_timechart`).
- `mcp` stays pinned `>=1.28,<2` until the v2 migration is done deliberately.

## Architecture in one breath

`server.py` (tool surface, FastMCP) → `cli.py` (argv construction) → `core/runner.py`
(subprocess) → real binary or mock (resolved by `core/config.py`; mode auto-detects) →
output → `parse.py` → TypedDicts from `core/models.py`; results registered in
`core/store.py` under short ids (`hs-0000`); comparisons via `core/compare.py` return a
verdict that `fail_on_regression` turns into a hard ToolError (the agentic-loop gate).

## Self-testing

`docs/SELF_TESTING.md` is the full story. Short form: `uv run pytest` is layers 1-4;
layer 5 is agentic — Workflow tool with `{scriptPath: ".claude/workflows/self-test.js"}`
(probes both servers over real stdio, adversarially verifies findings);
`optimize-project.js` is the test-gated self-improvement loop. Skills:
`profile-hotspots`, `optimize-loop`, `profiler-selftest`.
