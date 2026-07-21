---
name: profiler-selftest
description: Run, extend, or debug this repo's self-test pyramid — unit tests, in-memory MCP tests, stdio smoke, mock ground-truth e2e, and the agentic self-test workflow. Use for "run the self tests", "is the project healthy", or after changing server/mock/parser code.
---

# Profiler self-test

Everything is testable on any machine: the mock CLIs (`src/profiler_mcp/mocks/`) stand in
for the real profilers with byte-realistic output (see `docs/research/captures-*.md`).

## Fast path

```bash
uv run pytest            # layers 1-4: unit, in-memory MCP, stdio smoke, ground truth
uv run ruff check src tests
```

Both must be green before and after any change. If `pytest` is green but you changed mock
output shapes, also re-check parser fixtures — fixtures are verbatim vendor output and
must NEVER be edited to make a parser pass (fix the parser; fixtures only change when new
verbatim captures are added to `docs/research/`).

## The layers (docs/SELF_TESTING.md has detail)

| Layer | Where | Catches |
|---|---|---|
| 1 unit | `tests/test_core_*`, parser tests | parsing/logic bugs |
| 2 in-memory MCP | `tests/test_vtune_*`, `test_uprof_*` | tool schema/wiring bugs |
| 3 stdio smoke | `tests/test_stdio_smoke.py` | transport/entry-point bugs |
| 4 ground truth | `tests/test_ground_truth.py` | end-to-end attribution: profile the compiled `examples/workloads/hotspots` binary, assert `hot_compute` dominates per the sidecar model; seeded regression must fail `*_compare` |
| 5 agentic | `.claude/workflows/self-test.js` (Workflow tool) | LLM-facing ergonomics: unclear errors, oversized outputs, schema surprises |

## Layer 5: agentic self-test

Run via the Workflow tool with `{scriptPath: ".claude/workflows/self-test.js"}`. It runs
layers 1–4, then fans out probe agents that drive each server through MCP as a model
would (happy paths, error paths, fault-injected mocks via `MOCK_FAIL`), and adversarially
verifies every reported failure before surfacing it. Findings that survive verification
are real bugs or real ergonomics problems — feed them to
`.claude/workflows/optimize-project.js`.

## Debugging failures

- One mock's behavior is off → run it directly:
  `uv run python src/profiler_mcp/mocks/vtune_mock.py -collect hotspots -result-dir /tmp/r -- ./examples/workloads/hotspots --seconds 0.3`
- MCP layer failure → reproduce with the in-memory client (`create_connected_server_and_client_session`)
  in a scratch script before touching test code.
- Fault-injection paths: set `MOCK_FAIL=collect-perm|collect-hang|report-empty|bad-exit`.
- Determinism: mocks honor `MOCK_FIXED_TIME=<unix-sec>` for byte-stable timestamps.
