#!/usr/bin/env bash
# Audit pinned dependencies from uv.lock via OSV (pip-audit).
#
# Exports the same extras CI bootstrap installs (dev + api + obs), then runs
# pip-audit with --no-deps because uv export emits exact pins from the lockfile.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if [[ ! -f uv.lock ]]; then
  echo "deps-audit: missing uv.lock in $repo_root" >&2
  exit 1
fi

echo "deps-audit: scanning uv.lock (dev + api + obs extras) via OSV…"

uv export \
  --format requirements-txt \
  --no-hashes \
  --no-emit-project \
  --extra dev \
  --extra api \
  --extra obs \
  | uv run pip-audit \
    -r /dev/stdin \
    --no-deps \
    -s osv \
    "$@"
