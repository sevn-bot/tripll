# Bad fixture — dangling dependency

```toml
waveorch_format = 2
title = "Dangling dep fixture"
slug = "bad-dangling-dep"
base = "origin/main"
branch = "feature/bad-dangling-dep"

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
effort = "M"
role = "impl"
verify = ["make lint"]

[[waves]]
id = "Final"
title = "Final wave"
depends_on = ["W99"]
effort = "L"
role = "impl"
verify = ["make ci-resume"]
```

## Wave W0 — First wave

- [ ] **W0.1** Task.

## Wave Final — Final wave

- [ ] **Final.1** Final task.
