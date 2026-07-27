# Bad fixture — impl wave missing test-author dep

```toml
waveorch_format = 2
title = "Bad impl missing test dep"
slug = "bad-impl-missing-test-dep"
base = "origin/main"
branch = "feature/bad-impl-missing-test-dep"

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
title = "Test author"
depends_on = []
role = "test-author"
verify = ["make lint"]

[[waves]]
id = "W1"
title = "Impl without dep"
depends_on = []
role = "impl"
verify = ["make lint"]

[[waves]]
id = "Final"
title = "Integration gate"
depends_on = ["W1"]
role = "impl"
verify = ["make lint"]
```

## Wave W0 — Test author

- [ ] **W0.1** Bad fixture task.

## Wave W1 — Impl without dep

- [ ] **W1.1** Bad fixture task.

## Wave Final — Integration gate

- [ ] **Final.1** Bad fixture task.
