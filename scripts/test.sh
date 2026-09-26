#!/usr/bin/env bash
set -euo pipefail
BENCH_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$BENCH_ROOT"
exec python3 scripts/check.py "$@"
