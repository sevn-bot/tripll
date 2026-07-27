# Good fixture — waveorch format v2

```toml
waveorch_format = 2
title = "Good fixture plan"
slug = "good-fixture"
base = "origin/main"
branch = "feature/good-fixture"

[pipeline]
max_turns = 1

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
id = "W0"
title = "First wave"
depends_on = []
review_gate = true
effort = "M"
role = "impl"
verify = ["make lint", "make typecheck"]

[[waves]]
id = "Final"
title = "Integration gate"
depends_on = ["W0"]
effort = "L"
role = "impl"
verify = ["make ci-resume"]
```

## Wave W0 — First wave

- [ ] **W0.1** Example task for the good fixture.

## Wave Final — Integration gate

- [ ] **Final.1** Run integration verify targets.
