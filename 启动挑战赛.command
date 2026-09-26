#!/bin/zsh
set -eu
ARENA_PROJECT_DIR="${0:A:h}"
cd "$ARENA_PROJECT_DIR"
exec python3 "$ARENA_PROJECT_DIR/scripts/launch_arena.py" "$@"
