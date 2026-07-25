# Bad fixture — parent path ref

```toml
waveorch_format = 2
title = "Parent ref fixture"
slug = "bad-parent-ref"
base = "origin/main"
branch = "feature/bad-parent-ref"

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
```

## Wave W0 — First wave

- [ ] **W0.1** See [bad link](BAD_LINK_TARGET).
