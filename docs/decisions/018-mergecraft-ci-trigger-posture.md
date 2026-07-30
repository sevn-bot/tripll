# ADR 018 — mergeCraft CI trigger posture and pin-parity gate

**Status:** Accepted (2026-07-30, Wave W0); implemented W2
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
   `origin/main` and overridable by `TRIPLL_MERGECRAFT_PARITY_REF`. **Skip with warning and exit 0**
   when the ref is unreachable and `CI` is unset (offline `make check`). **Hard-fail when `CI` is set.**

3. **Bump order:** merge the workflow pin bump to the default branch **first**, then bump
   `MERGECRAFT_REF` in the Makefile. Documented in the operator runbook (W2.6).

4. **Adopt the upstream hardened workflow; do not hand-roll (R37).** When `alexhawat/mergeCraft`
   lands a fail-open `wait-for-ci` job, tripll adopts it. The job must poll check-runs for the head
   SHA, feed the outcome **and the `check_suite_id`** into the review prompt, and **fail open on
   every path** so a slow or absent CI run never blocks a review. No local copy now.

5. **Base-branch coverage:** `branches: [main]` is intentional (W2.4). Stacked `wave/*` and `feat/*`
   PRs that target each other get no mergeCraft review; tripll wave plans merge to `main`. Recorded
   as a workflow comment beside `branches:`.

## Option (b) — exact shape if `pull_request_target` is ever taken

Switching from option (a) to (b) is a lookup, not a rediscovery:

1. **Trigger:** replace `pull_request` with `pull_request_target` (same `types` and `branches`).
2. **Same-repo guard:** add `if: github.event.pull_request.head.repo.full_name == github.repository`
   on every step that uses repository secrets (`CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_API_KEY`).
   `pull_request` gets fork isolation for free; `pull_request_target` does not.
3. **Concurrency re-key:** under `pull_request_target`, `github.ref` resolves to the **default
   branch**, not the PR head. Replace `mergecraft.yml`'s current group
   `mergecraft-${{ github.workflow }}-${{ github.ref }}` with a PR-number key, e.g.
   `mergecraft-${{ github.event.pull_request.number }}`, so open PRs do not cancel each other.
4. **Pin-parity gate:** already topology-proof (R36) — reads the default-branch workflow ref via
   `git show`, not the working tree.
5. **Revisit required-check posture:** only take (b) when mergeCraft becomes a **required** branch
   ruleset check; until then (a) avoids secret exposure with no benefit.

## Rejected alternatives

| Alternative | Why rejected |
|-------------|--------------|
| **`pull_request_target` now** | Exposes repository secrets on every PR; requires a same-repo guard the current job lacks. Under `pull_request_target`, `github.ref` resolves to the default branch, collapsing `mergecraft.yml` concurrency groups across every open PR. No benefit while the review is advisory-only. |
| **Keeping the working-tree read for pin parity** | Correct only while trunk is the default branch; fails silently when topology changes. |
| **Always hard-failing when ref is unreachable** | Breaks offline `make check` for everyone to guard against a topology change that has not happened. |
| **Hand-rolling a local `wait-for-ci` job** | Easy to write, easy to get subtly wrong; two copies diverge from upstream. |

## Consequences

- W2 implements the topology-proof parity gate and workflow comments; no trigger change in W2.
- If mergeCraft ever becomes a required check, revisit `pull_request_target` using the option (b)
  checklist above.
- Operator runbook documents mergeCraft bump-order guidance (W2.6).
