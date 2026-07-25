# wave-plan template (waveorch format v3)

Copy to `your-feature-wave-plan.md` and fill in. Required machine block:
**`waveorch_format = 3`** TOML front matter plus optional `## Wave <id>` checklist bodies.

Run `tripll validate-plan <plan.md>` before dispatch.

**Normative:** typed `[[waves.depends_on]]` reasons, per-wave `[waves.outcome]` contracts, and
`targets` for one-writer enforcement. See `docs/decisions/003-plan-format-and-shape.md`.

## Path convention

In-repo file references must be **repo-root-relative** (worktree root = repo root):

- Use paths from the repository root: `src/…`, `docs/…`, `tests/…`, `.cursor/agents/…`.
- **Never** use `../`, `./`, or a leading `/` for in-repo paths.

## TOML schema (v3)

```toml
waveorch_format = 3
title = "Feature title"
slug = "feature-slug"
base = "main"
branch = "wave/feature-slug"
target_repo = "sevn-bot/tripll"          # factory may target any repo

[pipeline]
max_turns = 3
deadline = "6h"                          # run-level wall clock (exit 4)
budget_usd = 25.0                        # exit 3

[[waves]]
id = "W1"
title = "Author full test suite"
role = "test-author"
effort = "L"
targets = ["tests/test_feature.py"]
verify = ["make lint", "make typecheck"]

  [waves.outcome]
  required = ["tests/test_feature.py collects"]
  forbidden = ["impl wave edits tests/"]
  evidence = ["test_output"]

[[waves]]
id = "W2"
title = "First implementation wave"
role = "impl"
effort = "M"
targets = ["src/tripll/feature/module.py"]
verify = ["make ci-affected"]

  [[waves.depends_on]]
  wave = "W1"
  reason = "contract"                    # artifact | contract | gate
  detail = "un-xfail tests from W1"

  [waves.outcome]
  required = ["tests/test_feature.py::test_happy_path passes"]
  forbidden = ["new dependency in pyproject.toml"]
  evidence = ["test_output", "final_diff"]
```

### Typed dependency reasons (D19)

| reason | Meaning |
|--------|---------|
| `artifact` | downstream wave reads a file upstream wrote |
| `contract` | downstream un-xfails or satisfies upstream tests |
| `gate` | human or CI gate between waves |

Reason-less edges are **dropped** at compile time and reported in `fake-edge-report.md`.

### Stop rule (D20)

The compiler **refuses** plans that parallelise sequential work:

- Parallel waves whose targets are joined by a 1-hop `CALLS` path.
- Cross-cutting refactors split across parallel waves touching > 5 modules.
- Two parallel waves targeting the same file (one-writer, D21).

### Outcome contracts (D16)

Every impl wave should declare `[waves.outcome]` with `required`, `forbidden`, and `evidence`.
Graders decide completion — agents do not self-report done.

## Checklist body (optional markdown)

After the TOML block, add human checklist sections:

```markdown
## Wave W1 — author full test suite (test-author)

- [ ] **W1.1** Unit tests — happy + edge + error paths.
- [ ] **W1.2** Integration tests — module wiring.

## Wave W2 — first implementation wave (impl)

- [ ] **W2.1** Turn W1 xfails green; do not edit `tests/`.
```

## Compatibility

Legacy v1 (`## tripll execution graph`) and v2 (`waveorch_format = 2`) plans are read via
`tripll.plan.compat_v1_v2.read_legacy_plan` and emitted as v3 in memory with a one-time warning.

## Canonical invocation

```bash
make lint && make typecheck && make test
tripll run --plan your-feature-wave-plan.md
```
