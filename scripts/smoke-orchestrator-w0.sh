#!/usr/bin/env bash
# W0 orchestrator-mode smoke — validate example input set and run pytest parity (Final.4).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

SET="${SET:-orchestrator-mode-smoke}"
EXAMPLE_SRC="docs/examples/orchestrator-mode-input-set"
INPUT_DST="runs/input/${SET}"

echo "== seed input set: ${SET} =="
mkdir -p "$INPUT_DST"
cp "${EXAMPLE_SRC}/"*.md "$INPUT_DST/"

echo "== validate-set =="
make validate-set "SET=${SET}"

echo "== plan-set =="
make plan-set "SET=${SET}"

echo "== pytest orchestrator W0 smoke =="
uv run --extra dev pytest tests/test_orchestrator_mode_smoke.py -v --tb=short

echo ""
echo "Manual smoke (optional, requires cursor-agent):"
echo "  make run-set SET=${SET} PROVIDER=cursor_local MODEL=auto"
echo "  make status-watch RUN=<run-id>"
echo "  make serve   # open /runs/<run-id> — Orchestrator panel"
