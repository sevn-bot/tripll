# Bad fixture — verify without make prefix

```toml
waveorch_format = 2
title = "Verify nonmake fixture"
slug = "bad-verify-nonmake"
base = "origin/main"
branch = "feature/bad-verify-nonmake"

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
verify = ["pytest tests/"]
```

## Wave W0 — First wave

- [ ] **W0.1** Task.
