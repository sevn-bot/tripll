# Live fixture-repo E2E evidence (Gap 1 manual AC)

Date: 2026-07-28
Branch: `docs/live-fixture-e2e-evidence`
Fixture template: `tests/fixtures/delivery/minimal-repo/`

## Scope

Closes the manual checklist item left after PR #35: prove the operator delivery
path against a **real minimal git repo** (not the tripll checkout), with
documented evidence. Live GitHub push/merge remains manual.

## Fixture repo

| Item | Path |
|------|------|
| Template | `tests/fixtures/delivery/minimal-repo/` |
| Bootstrap helper | `tests/fixtures/delivery/bootstrap.py` |
| Wave plan | `docs/plans/delivery-smoke-wave-plan.md` (copied into runs input set) |
| Git branches | `main` + `test-pre` (integrate default base_ref) |
| Gate | `make ci-resume` (no-op pass) |

## Automated tiers (CI)

```bash
make test TESTS=tests/test_delivery_live_fixture.py
make test TESTS=tests/test_delivery_e2e.py
make test TESTS=tests/test_pr_loop.py
```

| Test | What it proves |
|------|----------------|
| `test_fixture_repo_run_integrate_deliver_dry_run` | Step 1 dry-run on fixture `TRIPLL_REPO_ROOT` |
| `test_fixture_repo_integrate_deliver_after_git_run` | Completed run → integrate branch → deliver (TRIPLL_PR_DRY_RUN) |
| `test_fixture_repo_operator_checklist` | Runbook section 8 steps 1-6 with stubbed `gh` |
| `test_delivery_e2e.py` | Same chain without fixture repo layout |

## Manual operator commands (offline)

```bash
uv run python -c "
from pathlib import Path
from tests.fixtures.delivery.bootstrap import bootstrap_minimal_repo, copy_delivery_smoke_input
from tripll.pipeline import RunsRoot
root = Path('/tmp/delivery-fixture')
bootstrap_minimal_repo(root)
runs = root / 'runs'
RunsRoot(runs).init()
copy_delivery_smoke_input(runs / 'input' / 'delivery-smoke')
print('fixture:', root)
"

export TRIPLL_REPO_ROOT=/tmp/delivery-fixture
export TRIPLL_PR_DRY_RUN=1

tripll run runs/input/delivery-smoke --integrate --deliver --dry-run --runs-root "$TRIPLL_REPO_ROOT/runs"
```

Sample dry-run output (2026-07-28):

```
[integrate] Branch  : tripll/integrate/delivery-smoke-20260728-153426 (off test-pre)
[integrate] Batch A: Delivery Smoke
             merge   : delivery-smoke
             gate    : make ci-resume
[deliver] push      : idempotency_key=push:delivery-smoke-20260728-153426
[deliver] open_pr   : idempotency_key=open_pr:delivery-smoke-20260728-153426
[deliver] merge     : human gate — tripll pr approve-merge (never auto-merge)
```

Post-deliver operator chain (stubbed in tests; manual with real PR number):

```bash
tripll pr shepherd --run <run-id> --phase deliver
tripll findings sync --pr <n> --run-id <run-id>
tripll pr shepherd --run <run-id> --phase investigate_and_fix
tripll pr status <run-id>
tripll pr approve-merge <run-id>
# Merge in GitHub UI or: gh pr merge (after approve-merge)
```

## Production fix discovered

**Bug:** `--integrate --deliver` after a completed run used `RunsRoot.run_dir()`
(processing/ only). The engine promotes finished runs to `processed/`, so
integrate/deliver failed to locate the run graph.

**Fix:** `cli._require_run_dir()` uses `RunsRoot.find_run_dir()` for integrate
and deliver phases.

## Blocked without live GitHub

| Step | Blocker |
|------|---------|
| `TRIPLL_PR_DRY_RUN=0` push to `origin` | Requires remote + credentials |
| `gh pr create` | Requires `gh auth` + GitHub repo |
| Real CI/review findings sync | Requires open PR with checks |
| Merge | Human gate + GitHub UI (by design, D15) |

## Validation

- `make lint` / `make typecheck`
- `pytest tests/test_delivery_live_fixture.py tests/test_delivery_e2e.py tests/test_pr_loop.py`
- `make ci-resume`
