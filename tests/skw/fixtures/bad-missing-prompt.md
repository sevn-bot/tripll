# Bad fixture — missing prompt file

```toml
waveorch_format = 2
title = "Missing prompt fixture"
slug = "bad-missing-prompt"
base = "origin/main"
branch = "feature/bad-missing-prompt"

[pipeline]
max_turns = 1

[pipeline.run]
agent = "wave-runner"
prompt = "prompts/missing-wave-runner.md"

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
```

## Wave W0 — First wave

- [ ] **W0.1** Task.
