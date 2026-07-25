# Bad fixture — two test-author waves

```toml
waveorch_format = 2
title = "Bad double test-author"
slug = "bad-double-test-author"
base = "origin/main"
branch = "feature/bad-double-test-author"

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
title = "Test author one"
depends_on = []
role = "test-author"
verify = ["make lint"]

[[waves]]
id = "W1"
title = "Test author two"
depends_on = []
role = "test-author"
verify = ["make lint"]

[[waves]]
id = "Final"
title = "Integration gate"
depends_on = ["W1"]
role = "impl"
verify = ["make lint"]
```

## Wave W0 — Test author one

- [ ] **W0.1** Bad fixture task.

## Wave W1 — Test author two

- [ ] **W1.1** Bad fixture task.

## Wave Final — Integration gate

- [ ] **Final.1** Bad fixture task.
