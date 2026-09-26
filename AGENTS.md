# Repository conventions

- This is a benchmark organizer repository. `repository/buggy/` and frontend `starter.html` contain intentional defects. Preserve them unless deliberately versioning the challenge.
- Follow each task's public behavior contract. Do not silently change task difficulty, score weights, hidden/visible boundaries, or baseline claims.
- Main verification: `./scripts/test.sh`. It starts real local HTTP services and worker processes and should clean them up after completion.
- Browser verification and independent visual judging are separate from CI. Pending scores stay null.
- Model keys come from environment variables. Never commit secrets, submissions, or local provider configurations.
- New code-track changes must keep service code and core regression using the same submitted engine implementation.
- When claiming a fix, preserve reproduction, diagnosis, changed behavior, self-tests, and full regression evidence.
- v0.2 defaults to the extreme profile; v0.1 artifacts and LEGACY_PROMPT.md remain explicit compatibility references. Never mix profile/scale/efficiency budgets in one ranking.
- Judge audit success is separate from candidate success. The extreme reference candidates are deliberately incomplete and may fail; do not turn those failures into artificial passes.
- The primary model-experiment flow is README -> independent Agent attempts -> sealed answers -> Codex-side grading. Do not grade an Agent's own claim of success.
- Unknown token/TTFT/internal-thinking measurements are null. Simulated or self-reported metrics cannot be used for official efficiency deductions without independent evidence.
