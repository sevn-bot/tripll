# Bad fixture — orphan heading

```toml
waveorch_format = 2
title = "Orphan heading fixture"
slug = "bad-orphan-heading"
base = "origin/main"
branch = "feature/bad-orphan-heading"

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
title = "Only wave"
depends_on = []
effort = "M"
role = "impl"
verify = ["make lint"]
```

## Wave W0 — Only wave

- [ ] **W0.1** Task.

## Wave Orphan — Not in graph

- [ ] **Orphan.1** Orphan task.
