# Smoke loop — throwaway one-wave plan (Final self-test)

**Status:** Throwaway (Final wave loop smoke only)
**Date:** 2026-06-24

Single-wave plan for `uv run skw run --wave …` convergence smoke. Uses ``scripts/smoke-agent.sh`` (auto-selected
when slug is ``smoke-loop``). Review writes ``verdict: pass`` with no new wave-file.

```toml
waveorch_format = 2
title  = "Smoke loop self-test"
slug   = "smoke-loop"
base   = "test-pre"
branch = "feature/skw-smoke-loop"

[pipeline]
max_turns = 1

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
id = "W1"
title = "Lint gate"
depends_on = []
effort = "S"
role = "impl"
verify = ["make lint"]
```

## Wave W1 — Lint gate

- [ ] **W1.1** Smoke-only: run verify target and exit (no product edits).
