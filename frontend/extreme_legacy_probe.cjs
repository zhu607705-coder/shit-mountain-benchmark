// Read-only execution of actual v0.1 F4 JavaScript. This is a scoped capability
// probe, not a claim that the legacy page implements the v2 adapter protocol.
const path = require('node:path');
const savedLog = console.log;
let context;
try {
  console.log = () => {};
  ({ context } = require('./F4/selftest.cjs'));
} finally {
  console.log = savedLog;
}
const shared = new Map();
const a = context(path.join(__dirname, 'F4/baseline.html'), shared);
const b = context(path.join(__dirname, 'F4/baseline.html'), shared);
a.run("patch('TASK-001',{title:'A first'})");
b.run('scan();reduce()');
const before = b.run("items.get('TASK-001').fields.title");
b.run("patch('TASK-001',{title:'B after observing A'})");
a.run('scan();reduce()');
const result = {
  task_id: 'F4',
  implementation: 'actual frontend/F4/baseline.html JavaScript',
  environment: 'Node VM with DOM/storage doubles, not native browser',
  scenario: 'B observes A before making a same-field successor edit',
  observed_a_before_edit: before,
  final_value: a.run("items.get('TASK-001').fields.title"),
  legacy_history_warning: a.run("items.get('TASK-001').conflicts.has('title')"),
  new_contract_requires_exact_causal_concurrency: true,
  concurrency_in_this_history: false,
  gap_confirmed: before === 'A first' && a.run("items.get('TASK-001').conflicts.has('title')"),
  interpretation: 'Legacy history warning is valid under v0.1 but cannot serve as the new exact concurrency indicator. This is not a full v2 baseline score.'
};
console.log(JSON.stringify(result, null, 2));
if (!result.gap_confirmed || result.final_value !== 'B after observing A') process.exitCode = 1;
