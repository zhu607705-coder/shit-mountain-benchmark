# v0.2 Extreme challenge implementation plan

**Goal:** Upgrade the unified twelve tasks with auditable >=10x workload dimensions and additional coupled reasoning mechanisms; provide executable generators, evaluators, witness/regression checks and honest weak-baseline evidence. Do not claim any model is provably unable to solve them.

**Architecture:** Preserve the v0.1 release and contracts as an explicit legacy profile. Each track adds an extreme runner with `--task`, `--scale smoke|full`, `--seed`, `--output`, optional `--export`, and `--submission` where its candidate interface supports evaluation. Small smoke instances retain the new mechanisms; full instances instantiate declared workload growth. Root tooling unifies exports, runs, manifests, provenance, calibration and CI. A baseline failure is a candidate result, not an evaluator failure.

**Tech stack:** Python standard library, Node.js, actual subprocess/HTTP/filesystem environments where appropriate, GitHub Actions. Real browser checks remain separate from Node logic checks. No paid model calls without supplied configuration and authorization.

## Track ownership

1. Reasoning worker owns `reasoning/extreme.py`, its helpers/tests and `reasoning/R*/extreme/`. Implement changed planning/information dynamics, independent tiny-instance checks, nonanticipation, public/private information boundaries, measured scale ratios and baseline losses. Root does not edit these concurrently.
2. Code worker owns `code/extreme.py`, its helpers/tests and `code/C*/extreme/`. Implement fault interaction tests and real persistence/concurrency probes; preserve legacy entrypoints. Provide reproducible baseline failures and feasible tiny witnesses, with no weakening of public correctness criteria.
3. Frontend worker owns `frontend/extreme.py`, its helpers/tests and `frontend/F*/extreme/`. Implement deterministic multi-actor traces, semantic result verification and workload generation; distinguish state-engine verification from browser rendering and usability. Do not fabricate browser scores.
4. Root owns versioned registry, `scripts/extreme.py`, integration CLI, overall difficulty/acceptance report, CI and release. Verify each worker's runtime evidence independently and retain unresolved calibration explicitly.

## Acceptance and execution

- Each full task declares at least one instantiated workload dimension >=10x its v0.1 counterpart. Report measured counts, not an unsupported ratio of intelligence or reasoning difficulty.
- Each task introduces at least two interacting mechanisms beyond simple size increases. Explain the decision dependencies and legal information available at each phase.
- Judges reject malformed inputs and impossible actions, have small known-feasible witnesses/independent invariants, and do not reward deleting functionality.
- Run track regression commands, full instance generation, and bounded baseline probes. Record generated-only or unexecuted workloads as such.
- Run legacy verification to preserve v0.1 compatibility, then extreme smoke verification in Linux/macOS CI. Full long-running stress is an explicit command/profile rather than a mislabeled smoke pass.
- Review the patch, push the feature branch, create and attach a PR, wait for actual CI, merge the authorized upgrade, and publish a versioned release only with verified artifacts.
- Success means a runnable, auditable hard challenge suite, not that the author solved every task or that all reference submissions passed.

## Unified arena extension

The user's latest requirement adds a single local launcher for task selection, random draws, six difficulty tiers, scoped prompt segments, sealed answer deposits and independent scoring. Tier names are 青铜、白银、黄金、钻石、王者、噩梦. Actual scope, sample count, fixture scale and budgets are committed before the attempt. All participants in one match reuse that committed draw; relative marks never mean absolute completion.

- Rules/judge worker owns `arena/rules.py`, `arena/judge.py` and their tests and difficulty rationale.
- Backend worker owns local HTTP endpoints, private state, safe deposits, background grading and launchers.
- UI worker owns `arena/web/` only. Root owns browser QA, documentation, CI integration and release.
- Root independently tests draw -> public README -> sealed submission -> grading -> score display, alongside malformed/tampered submission regressions. Browser/UI review and unverified model timing remain pending when evidence is absent.
- The existing README batch workflow remains available for preregistered multi-prompt/multi-round studies. No real model call is claimed merely because a plan with 108 attempts was prepared.
