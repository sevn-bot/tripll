# Pipeline fixture — three-wave graph with test-author + review gate

```toml
waveorch_format = 2
title = "Pipeline three-wave fixture"
slug = "pipeline-three-wave"
base = "origin/main"
branch = "feature/pipeline-three-wave"

[pipeline]
max_turns = 3

[pipeline.run]
agent = "wave-runner"
prompt = "prompts/wave-runner.md"

[pipeline.review]
agent = "reviewer"
prompt = "prompts/reviewer.md"

[pipeline.generate]
agent = "post-review-wave-generator"
prompt = "prompts/post-review-wave-generator.md"

[[waves]]
id = "W1"
title = "Test author wave"
depends_on = []
role = "test-author"
verify = ["make -C spec-kit-wave test"]

[[waves]]
id = "W2"
title = "Impl with review gate"
depends_on = ["W1"]
review_gate = true
effort = "M"
role = "impl"
verify = ["make -C spec-kit-wave validate-selftest"]

[[waves]]
id = "Final"
title = "Integration gate"
depends_on = ["W2"]
effort = "L"
role = "impl"
verify = ["make -C spec-kit-wave validate-selftest"]
```

## Wave W1 — Test author wave

- [x] **W1.1** Completed test-author task.
- [ ] **W1.2** Pending test-author task.

## Wave W2 — Impl with review gate

- [ ] **W2.1** Pending impl task.

## Wave Final — Integration gate

- [ ] **Final.1** Pending final task.
