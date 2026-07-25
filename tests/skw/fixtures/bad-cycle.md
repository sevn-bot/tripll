# Bad fixture — dependency cycle

```toml
waveorch_format = 2
title = "Cycle fixture"
slug = "bad-cycle"
base = "origin/main"
branch = "feature/bad-cycle"

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
title = "Wave A"
depends_on = ["Final"]
effort = "M"
role = "impl"
verify = ["make lint"]

[[waves]]
id = "Final"
title = "Wave B"
depends_on = ["W0"]
effort = "L"
role = "impl"
verify = ["make ci-resume"]
```

## Wave W0 — Wave A

- [ ] **W0.1** Task A.

## Wave Final — Wave B

- [ ] **Final.1** Task B.
