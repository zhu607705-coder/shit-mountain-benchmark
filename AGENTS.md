# Repository conventions

- This is a benchmark organizer repository. `repository/buggy/` and frontend `starter.html` contain intentional defects. Preserve them unless deliberately versioning the challenge.
- Follow each task's public behavior contract. Do not silently change task difficulty, score weights, hidden/visible boundaries, or baseline claims.
- Main verification: `./scripts/test.sh`. It starts real local HTTP services and worker processes and should clean them up after completion.
- Browser verification and independent visual judging are separate from CI. Pending scores stay null.
- Model keys come from environment variables. Never commit secrets, submissions, or local provider configurations.
- New code-track changes must keep service code and core regression using the same submitted engine implementation.
- When claiming a fix, preserve reproduction, diagnosis, changed behavior, self-tests, and full regression evidence.
