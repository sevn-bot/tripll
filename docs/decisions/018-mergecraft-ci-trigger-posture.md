# ADR 018 — mergeCraft CI trigger posture and pin-parity gate

**Status:** Accepted (2026-07-30, Wave W0)
**Decisions:** R35, R36, R37
**Issues:** [#59](https://github.com/sevn-bot/tripll/issues/59)

## Context

`.github/workflows/mergecraft.yml` triggers on `pull_request` targeting `main`. Issue #59 asks for
an explicit decision on trigger posture and a pin-parity gate that remains correct when GitHub
resolves workflow definitions from the default branch (Nov-2025 policy, effective 2025-12-08).

`scripts/check_mergecraft_ref_parity.py` today compares the **working-tree** workflow pin against
`Makefile`'s `MERGECRAFT_REF`. That is correct only while `main` is both trunk and default branch.

The review fires on `synchronize` with no lint/typecheck/test signal and no `check_suite_id`, so it
speculates about mechanical failures the gates would have caught.

## Decision

1. **Keep `pull_request` trigger; keep mergeCraft non-required (R35).** Option (a) from #59. The
   workflow carries a comment stating this decision. `pull_request_target` is deferred until the
   review becomes a **required** check — it is not today.

2. **Pin-parity gate reads the ref GitHub actually resolves (R36).** `check_mergecraft_ref_parity.py`
   reads the workflow pin from `git show <ref>:.github/workflows/mergecraft.yml`, defaulting to
   `origin/main` and overridable by env var. **Skip with warning and exit 0** when the ref is
   unreachable and `CI` is unset (offline `make check`). **Hard-fail when `CI` is set.**

3. **Bump order:** merge the workflow pin bump to the default branch **first**, then bump
   `MERGECRAFT_REF` in the Makefile. W2 documents this in the operator runbook.

4. **Adopt the upstream hardened workflow; do not hand-roll (R37).** When `alexhawat/mergeCraft`
   lands a fail-open `wait-for-ci` job, tripll adopts it. No local copy now.

5. **Base-branch coverage:** decide in W2 whether `branches: [main]` is intentional or should be
   widened; record the decision as a workflow comment.

## Rejected alternatives

| Alternative | Why rejected |
|-------------|--------------|
| **`pull_request_target` now** | Exposes repository secrets on every PR; requires a same-repo guard the current job lacks. Under `pull_request_target`, `github.ref` resolves to the default branch, collapsing `mergecraft.yml` concurrency groups across every open PR. No benefit while the review is advisory-only. |
| **Keeping the working-tree read for pin parity** | Correct only while trunk is the default branch; fails silently when topology changes. |
| **Always hard-failing when ref is unreachable** | Breaks offline `make check` for everyone to guard against a topology change that has not happened. |
| **Hand-rolling a local `wait-for-ci` job** | Easy to write, easy to get subtly wrong; two copies diverge from upstream. |

## Consequences

- W2 implements the topology-proof parity gate and workflow comments; no trigger change in W2.
- If mergeCraft ever becomes a required check, revisit `pull_request_target` with same-repo guard
  and PR-number concurrency — documented here as the path from (a) to (b).
- Operator runbook gains mergeCraft bump-order guidance (W2.6).
