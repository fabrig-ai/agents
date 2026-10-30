#!/bin/bash
# Usage: tools/check.sh [--tier gate|periodic] [--changed BASE] [FILES ...]
# --json PATH also saves the measured results. Budgets live in tools/gate.toml.
set -euo pipefail
self=$(realpath -- "${BASH_SOURCE[0]}")
cd -- "$(dirname -- "$self")/.."
if [[ -z ${AGENTS_GATE_HELD:-} ]]; then
    lock=${AGENTS_GATE_LOCK:-$HOME/.local/state/agents-gate.lock}
    mkdir -p -- "$(dirname -- "$lock")"
    export AGENTS_GATE_HELD=1
    flock -n -o "$lock" true || echo "check.sh: waiting for another agents gate on this host ($lock)" >&2
    exec flock -o "$lock" bash "$self" "$@"
fi
export PYTHONDONTWRITEBYTECODE=1
bash -n tools/check.sh
exec python3 -I -B tools/gate.py "$@"
