#!/usr/bin/env bash
# Block `git clean -x`/`-X` in tripll. Safe alternative: git clean -fd
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

for arg in "$@"; do
  case "$arg" in
    -*) ;;
    *) continue ;;
  esac
  if [[ "$arg" == *x* ]] || [[ "$arg" == *X* ]]; then
    cat >&2 <<EOF
BLOCKED: git clean with -x or -X in $(basename "$repo_root")

Deletes gitignored local-only trees (e.g. .ignorelocal/, operator plans, design docs).

Safe: git clean -fd  |  git clean -fd -- path/

Use the repo bin/git wrapper: export PATH="\$PWD/bin:\$PATH"
EOF
    exit 1
  fi
done

exec git -c "alias.clean=" clean "$@"
