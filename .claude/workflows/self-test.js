// Agentic self-test for profiler-mcp (layer 5 of docs/SELF_TESTING.md).
// Run with the Workflow tool: {scriptPath: ".claude/workflows/self-test.js"}
// Optional args: {skipDeterministic: true} to go straight to probing.
//
// Layers 1-4 run as one deterministic gate; then probe agents drive both MCP
// servers over real stdio the way a model would; every failure is
// adversarially verified before it may appear in the final report.

export const meta = {
  name: 'profiler-selftest',
  description: 'Full self-test: pytest gate, then agentic MCP probes with adversarial verification',
  whenToUse: 'After changing server/mock/parser code, or to assess project health end to end.',
  phases: [
    { title: 'Gate', detail: 'pytest + ruff (layers 1-4)' },
    { title: 'Probe', detail: 'agents drive both servers over stdio MCP' },
    { title: 'Verify', detail: 'adversarial check of every reported failure' },
  ],
}

// Repo root: defaults to the current working directory (where the Workflow tool runs
// this script — the project root). Pass args {repo: "/abs/path"} to override.
const REPO = (typeof args === 'object' && args && args.repo) || '.'

const GATE_SCHEMA = {
  type: 'object',
  properties: {
    pytest_passed: { type: 'boolean' },
    ruff_passed: { type: 'boolean' },
    failures: { type: 'array', items: { type: 'string' } },
    tests_run: { type: 'number' },
  },
  required: ['pytest_passed', 'ruff_passed', 'failures', 'tests_run'],
}

const PROBE_SCHEMA = {
  type: 'object',
  properties: {
    probe: { type: 'string' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          title: { type: 'string' },
          severity: { type: 'string', enum: ['bug', 'ergonomics', 'info'] },
          evidence: { type: 'string', description: 'Exact tool call, exact response/error observed' },
          repro: { type: 'string', description: 'Minimal steps to reproduce' },
        },
        required: ['title', 'severity', 'evidence', 'repro'],
      },
    },
    tool_calls_made: { type: 'number' },
  },
  required: ['probe', 'findings', 'tool_calls_made'],
}

const VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    refuted: { type: 'boolean' },
    reasoning: { type: 'string' },
  },
  required: ['refuted', 'reasoning'],
}

const DRIVER_NOTE = `Drive the server over REAL stdio MCP: write a scratch Python script (in a temp dir, not the repo) using the official SDK client:
  from mcp.client.stdio import stdio_client, StdioServerParameters
  from mcp.client.session import ClientSession
spawning the server with command "uv", args ["run", "<vtune-mcp|uprof-mcp>"], cwd ${REPO}, env including PROFILER_MCP_MODE=mock and a fresh PROFILER_MCP_RESULTS_DIR under /tmp. Initialize, then make tool calls and inspect structuredContent. Compile the workload first if needed: make -C ${REPO}/examples/workloads. Judge responses AS AN LLM CONSUMER: is the error actionable? is the output within sane token size (<8k tokens)? does the schema match what the tool docstring promises? Report only what you actually observed — include verbatim responses as evidence.`

if (!(args && args.skipDeterministic)) {
  phase('Gate')
  const gate = await agent(
    `In ${REPO} run 'uv run pytest -q' and 'uv run ruff check src tests'. Report results exactly — count tests, list every failure with its assertion message. Do NOT fix anything.`,
    { label: 'gate:pytest+ruff', phase: 'Gate', schema: GATE_SCHEMA }
  )
  if (gate && (!gate.pytest_passed || !gate.ruff_passed)) {
    return { gate, probes: null, note: 'Deterministic gate failed — fix layers 1-4 before agentic probing.' }
  }
  log(`Gate green (${gate ? gate.tests_run : '?'} tests)`)
}

phase('Probe')
const PROBES = [
  { key: 'vtune-happy', prompt: `Probe the vtune MCP server, happy paths: vtune_check; vtune_collect analysis=hotspots on the compiled workload (command=[".../examples/workloads/hotspots","--seconds","1"], absolute path); vtune_list_results; vtune_report_summary; vtune_report_hotspots (top_n 3 and default); vtune_report_raw report_type=summary; collect a second result with ["--only","compute"] and vtune_compare both ways. Check: attribution matches the sidecar model, percents sum sensibly, result ids stable, mock-mode warnings present.` },
  { key: 'vtune-errors', prompt: `Probe the vtune MCP server, error paths: unknown result_id in every report tool; vtune_collect with BOTH command and pid; with NEITHER; pid without duration_sec; unknown analysis type with and without allow_unknown; vtune_report_raw with an unknown report type; MOCK_FAIL=collect-perm and MOCK_FAIL=bad-exit in the server env (restart server between). Every error must be a proper MCP tool error whose text tells the model what to do next — flag any raw traceback, any silent success, any error that dead-ends.` },
  { key: 'uprof-happy', prompt: `Probe the uprof MCP server, happy paths: uprof_check; uprof_system_info; uprof_collect config=hotspots on the compiled workload; uprof_list_results; uprof_report_summary; uprof_report_hotspots; uprof_report_raw; uprof_timechart events=["power"] duration_sec=2; second collect with ["--only","memory"] and uprof_compare. Check attribution vs sidecar, session-dir discovery, mode stamps.` },
  { key: 'uprof-errors', prompt: `Probe the uprof MCP server, error paths: bad result ids; command+pid conflicts; pid without duration; unknown config with/without allow_unknown; group_by without detail on raw report if exposed; timechart with interval_ms=5 (below uProf's 10ms floor); MOCK_FAIL=collect-perm and report-empty (restart between). Same bar: every error actionable, no tracebacks, no dead ends.` },
  { key: 'token-audit', prompt: `Probe BOTH servers for token discipline: call every report tool at default settings and at extremes (top_n=100, raw reports) against a hotspots collection of the workload. Measure the byte size of each structuredContent. Flag any tool whose default response exceeds ~8k tokens (~32kB), any unbounded list, any place truncation happens silently without a truncated flag or note.` },
]
const probeResults = await parallel(
  PROBES.map(p => () => agent(`${p.prompt}\n\n${DRIVER_NOTE}`, { label: `probe:${p.key}`, phase: 'Probe', schema: PROBE_SCHEMA }))
)

phase('Verify')
const allFindings = probeResults.filter(Boolean).flatMap(r => r.findings.map(f => ({ ...f, probe: r.probe })))
const serious = allFindings.filter(f => f.severity !== 'info')
log(`${allFindings.length} findings, ${serious.length} non-info — verifying`)
const verified = await parallel(
  serious.map(f => () =>
    agent(
      `Adversarially verify this finding against ${REPO}. Try to REFUTE it: re-run the repro exactly (${DRIVER_NOTE}), check whether the behavior is actually documented/intended (docstrings, docs/DESIGN.md), whether the probe misused the tool. Default to refuted=true if you cannot reproduce.\n\nFINDING: ${f.title}\nSEVERITY: ${f.severity}\nEVIDENCE: ${f.evidence}\nREPRO: ${f.repro}`,
      { label: `verify:${f.title.slice(0, 40)}`, phase: 'Verify', schema: VERDICT_SCHEMA }
    ).then(v => ({ finding: f, verdict: v }))
  )
)

const confirmed = verified.filter(Boolean).filter(v => v.verdict && !v.verdict.refuted)
return {
  gate: 'green',
  probes_run: PROBES.length,
  findings_total: allFindings.length,
  confirmed: confirmed.map(v => v.finding),
  refuted: verified.filter(Boolean).filter(v => v.verdict && v.verdict.refuted).map(v => v.finding.title),
  info: allFindings.filter(f => f.severity === 'info'),
}
