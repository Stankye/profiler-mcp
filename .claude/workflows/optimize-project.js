// Self-optimization loop for profiler-mcp: because the project can test itself
// (self-test.js), it can also improve itself with the tests as the safety net.
// Run with the Workflow tool: {scriptPath: ".claude/workflows/optimize-project.js"}
// Optional args: {dimensions: ["ergonomics", ...]} to restrict the sweep.
//
// find -> adversarial verify -> apply (test-gated, one agent per finding) -> re-gate.
// Nothing is kept unless the full deterministic suite stays green.

export const meta = {
  name: 'optimize-project',
  description: 'Self-test, then find/verify/apply improvements to profiler-mcp, gated by the test suite',
  whenToUse: 'Periodic project health + improvement pass, or after self-test.js reports confirmed findings.',
  phases: [
    { title: 'Self-test', detail: 'runs self-test.js as a child workflow' },
    { title: 'Find', detail: 'improvement miners per dimension' },
    { title: 'Judge', detail: 'adversarial verification of each proposal' },
    { title: 'Apply', detail: 'test-gated application, sequential' },
    { title: 'Re-gate', detail: 'full suite must stay green' },
  ],
}

// Repo root: defaults to the current working directory (where the Workflow tool runs
// this script — the project root). Pass args {repo: "/abs/path"} to override.
const REPO = (typeof args === 'object' && args && args.repo) || '.'

const PROPOSAL_SCHEMA = {
  type: 'object',
  properties: {
    proposals: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          title: { type: 'string' },
          dimension: { type: 'string' },
          files: { type: 'array', items: { type: 'string' } },
          problem: { type: 'string', description: 'Evidence: what is wrong today, concretely' },
          change: { type: 'string', description: 'Exact proposed change, small enough for one agent to apply' },
          risk: { type: 'string', enum: ['low', 'medium', 'high'] },
        },
        required: ['title', 'dimension', 'files', 'problem', 'change', 'risk'],
      },
    },
  },
  required: ['proposals'],
}

const JUDGE_SCHEMA = {
  type: 'object',
  properties: {
    approve: { type: 'boolean' },
    reasoning: { type: 'string' },
  },
  required: ['approve', 'reasoning'],
}

const APPLY_SCHEMA = {
  type: 'object',
  properties: {
    applied: { type: 'boolean' },
    tests_green: { type: 'boolean' },
    what_changed: { type: 'string' },
  },
  required: ['applied', 'tests_green', 'what_changed'],
}

phase('Self-test')
const selftest = await workflow({ scriptPath: '.claude/workflows/self-test.js' })
const confirmedIssues = (selftest && selftest.confirmed) || []
log(`Self-test: ${confirmedIssues.length} confirmed findings feed the improvement pass`)

phase('Find')
const ALL_DIMENSIONS = [
  { key: 'ergonomics', prompt: 'LLM-facing tool ergonomics: read both server.py files as if you were a model choosing and calling tools. Docstrings that under-explain, parameters that invite misuse, error messages that dead-end, missing mock-mode caveats, inconsistencies between the vtune and uprof surfaces.' },
  { key: 'fidelity', prompt: 'Mock fidelity: diff src/profiler_mcp/mocks/* against docs/research/captures-*.md byte-shape specs. Any stdout line, CSV header, section order, or quoting the mocks get wrong vs the verbatim captures.' },
  { key: 'simplify', prompt: 'Code quality: duplication between the two server modules that belongs in core/, dead code, over-clever parsing, missing edge-case handling in parse.py (malformed lines, empty reports). Do NOT propose adding features.' },
  { key: 'coverage', prompt: 'Test coverage gaps: read tests/ vs src/. Which behaviors documented in docstrings/DESIGN.md have no test? Fault-injection paths untested? Compare-verdict edge cases (zero baseline, added/removed functions)?' },
  { key: 'docs', prompt: 'Doc accuracy: README, CLAUDE.md, docs/*, skills. Claims that no longer match the code (tool names, env vars, commands). Missing setup steps a new user would hit.' },
]
const wanted = args && Array.isArray(args.dimensions) && args.dimensions.length
  ? ALL_DIMENSIONS.filter(d => args.dimensions.includes(d.key))
  : ALL_DIMENSIONS

const seedNote = confirmedIssues.length
  ? `\n\nConfirmed findings from the agentic self-test — turn any that fit your dimension into proposals:\n${confirmedIssues.map(f => `- ${f.title}: ${f.evidence}`).join('\n')}`
  : ''

const found = await parallel(
  wanted.map(d => () =>
    agent(
      `You are an improvement miner for ${REPO}, dimension: ${d.key}.\n${d.prompt}${seedNote}\n\nRead the actual files; cite file:line evidence in each proposal's problem field. 0-5 proposals, each independently applicable and small. Do not modify anything.`,
      { label: `find:${d.key}`, phase: 'Find', schema: PROPOSAL_SCHEMA }
    )
  )
)
const proposals = found.filter(Boolean).flatMap(r => r.proposals)
log(`${proposals.length} proposals mined`)
if (!proposals.length) return { selftest, applied: [], note: 'Nothing to improve.' }

phase('Judge')
const judged = await parallel(
  proposals.map(p => () =>
    agent(
      `Adversarially judge this improvement proposal for ${REPO}. Verify the problem evidence yourself (read the cited files). Reject if: evidence wrong or stale, change risks breaking the verbatim-fixture contract (fixtures are vendor ground truth and must never change to fit code), scope creep, or high risk with mild payoff. Approve only what you would merge.\n\n${JSON.stringify(p, null, 1)}`,
      { label: `judge:${p.title.slice(0, 40)}`, phase: 'Judge', schema: JUDGE_SCHEMA }
    ).then(v => ({ proposal: p, judge: v }))
  )
)
const approved = judged.filter(Boolean).filter(j => j.judge && j.judge.approve).map(j => j.proposal)
log(`${approved.length}/${proposals.length} approved`)

phase('Apply')
// Sequential on purpose: each application re-runs the suite before the next starts,
// so a bad change is caught and reverted in isolation.
const applied = []
for (const p of approved) {
  const r = await agent(
    `Apply this approved change to ${REPO}, touching ONLY ${p.files.join(', ')}:\n${JSON.stringify(p, null, 1)}\n\nThen run 'uv run pytest -q' and 'uv run ruff check src tests'. If anything fails and you cannot make it green while staying in scope, REVERT your edits completely and report applied=false. Never edit tests/fixtures/* or docs/research/*.`,
    { label: `apply:${p.title.slice(0, 40)}`, phase: 'Apply', schema: APPLY_SCHEMA }
  )
  if (r) applied.push({ title: p.title, ...r })
}

phase('Re-gate')
const regate = await agent(
  `In ${REPO} run 'uv run pytest -q' and 'uv run ruff check src tests'. Report pass/fail and any failure output verbatim. Do not fix anything.`,
  { label: 'regate', phase: 'Re-gate', schema: { type: 'object', properties: { green: { type: 'boolean' }, detail: { type: 'string' } }, required: ['green', 'detail'] } }
)

return {
  selftest_confirmed: confirmedIssues,
  proposals: proposals.length,
  approved: approved.length,
  applied,
  final_gate: regate,
}
