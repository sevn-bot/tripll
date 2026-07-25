# Example wave plan — tier-B quality remediation

**Status:** Example (copy and adapt)
**Date:** 2026-06-24

Runnable reference wave-file for the spec-kit-wave kit. Uses the default **thermo**
review pipeline (D3). Demonstrates the **tests-first** model: one `test-author` wave (W1) before
impl waves. Validate before dispatch:

```bash
make validate WAVE=waves/example-wave-plan.md
```

```toml
waveorch_format = 2
title  = "Tier-B quality remediation"
slug   = "tier-b-quality"
base   = "test-pre"
branch = "feature/spec-kit-wave-kit"

[pipeline]
max_turns = 3

[pipeline.run]
agent = "wave-runner"
prompt = "prompts/wave-runner.md"

[pipeline.review]
agent = "reviewer"
prompt = "prompts/reviewer.md"

[pipeline.review.inputs]
plugin = "thermo"

[pipeline.generate]
agent = "post-review-wave-generator"
prompt = "prompts/post-review-wave-generator.md"

[[waves]]
id = "W0"
title = "Design + scaffolding"
depends_on = []
review_gate = true
effort = "M"
role = "impl"
verify = ["make validate-selftest", "make check-deps"]

[[waves]]
id = "W1"
title = "Validator test suite (tests-first)"
depends_on = ["W0"]
effort = "M"
role = "test-author"
verify = ["make validate-selftest"]

[[waves]]
id = "W2"
title = "Renderer smoke"
depends_on = ["W1"]
effort = "S"
role = "impl"
verify = ["make render-all"]

[[waves]]
id = "Final"
title = "Integration gate"
depends_on = ["W2"]
effort = "M"
role = "impl"
verify = ["make validate-selftest"]
```

## Wave W0 — Design + scaffolding

- [ ] **W0.1** Read `wave-plan-template.md` and confirm the v2 TOML contract matches this file.
- [ ] **W0.2** Run `make validate-selftest` and `make check-deps` from the kit directory.
- [ ] **W0.5** **Review gate:** operator sign-off before wave execution continues.

## Wave W1 — Validator test suite (tests-first)

- [ ] **W1.1** Extend `tests/test_validate.py` with cases for test-author ordering rules (test-creator wave only).
- [ ] **W1.2** Run `make validate-selftest` — collection and lint clean; new assertions may be RED until W2.

## Wave W2 — Renderer smoke

- [ ] **W2.1** Run `make render-all WAVE=waves/example-wave-plan.md` — all four stages must render with no leftover placeholders.
- [ ] **W2.2** Confirm `make render WAVE=waves/example-wave-plan.md STAGE=run WAVE_ID=W1` renders the test-creator prompt.

## Wave Final — Integration gate

- [ ] **Final.1** Re-run `make validate-selftest` and confirm the active wave-file still validates clean.
