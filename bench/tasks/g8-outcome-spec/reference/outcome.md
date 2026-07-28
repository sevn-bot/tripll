# Outcome contract reference (G8 bench)

## Contract block {#contract}

An impl wave outcome contract must declare:

- **required** — observable behaviours the verifier can check without implementer testimony.
- **forbidden** — regressions that fail the wave even when required checks pass.
- **verify** — Make targets run by the isolated `wave-verifier` after the quality loop.

Quality gauntlet rounds are additive; they never replace correctness verify.

When `[waves.outcome.reference]` is present, the critic compares build artifacts to the
reference path using the plan's `comparison` mode until `stop_when` is satisfied.
