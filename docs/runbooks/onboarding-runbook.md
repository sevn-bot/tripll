# Onboarding runbook

Operator guide for bringing repositories under tripll — **brownfield** (existing repo)
and **greenfield** (new project). Machine-level provider config is separate from
repo-level layout.

## Commands

| Command | Scope | When |
|---------|-------|------|
| `tripll setup` | Machine (`~/.config/tripll/config.toml`) | Once per workstation |
| `tripll doctor` | Machine + repo | Before first dispatch |
| `tripll init` | Existing repo | Brownfield onboarding |
| `tripll new` | New directory | Greenfield scaffold |

## Brownfield path (`tripll init`)

Run from the **target repository root** (not the tripll checkout):

```bash
cd ~/code/my-project
tripll init
tripll doctor
```

### What `init` writes

| Artefact | Purpose |
|----------|---------|
| `tripll.toml` | Repo layout: `specs_dir`, `prds_dir`, `plans_dir`, detected tooling |
| `docs/specs/` | Starter spec scaffold (SKW frontmatter + required H2 sections) |
| `docs/prds/` | Starter PRD scaffold |
| `docs/plans/*-wave-plan.md` | Packaged **v3** wave-plan starter (`waveorch_format = 3`) |
| `docs/evaluation-<date>.md` | Repo assessment with **file:line evidence** per finding |
| `docs/architecture-review-*.html` | Self-contained HTML companion (architecture skill renderer) |
| `.tripll/graph.db` | Code graph from `graph extract` |
| `.tripll/runs/` | Input/processing/processed/failed folders for dispatch (legacy `runs/` kept when present) |

### Safe re-runs

`tripll init` is **idempotent**:

- Existing `tripll.toml`, specs, PRDs, and plans are **not overwritten**.
- Gaps are filled (missing runs dirs, missing evaluation for today when absent).
- Pass `--force` to overwrite scaffolds — use only when you intend to reset.

```bash
tripll init              # reconcile; preserve operator edits
tripll init --force      # overwrite scaffolds (destructive)
```

### Reading the evaluation

The evaluation markdown follows a chronological map, then per-area sections:

- **What works** — signals that are already healthy.
- **Issues / Missing / Stubs** — table rows with `file:line` evidence (never guesswork).

Use it to decide which waves to plan first. Cross-check with `tripll doctor` for
provider readiness before `tripll run`.

### Agent-assisted spec path

Brownfield init emits deterministic scaffolds. For LLM-assisted spec authoring,
use the SKW front-end stages (`specify`, `clarify`, `plan`, `wayfinder`,
`prd-author`, `wave-generator`) via `tripll.onboard.emitters.render_spec_prompt`.

## Greenfield path (`tripll new`)

Create a new project directory with a Python skeleton, tripll config, and starter
docs — then plan waves against it.

```bash
mkdir -p ~/code && cd ~/code
tripll new my-project
cd my-project
tripll doctor
make check
tripll validate-plan docs/plans/*-wave-plan.md
```

### What `new` writes

Everything from the brownfield table **plus** the project skeleton:

| Artefact | Purpose |
|----------|---------|
| `pyproject.toml`, `Makefile`, `src/`, `tests/` | Minimal Python package passing `make check` |
| `.git/` | Fresh git repository (when git is available) |

`tripll new` uses **packaged offline templates** by default — no network required.
Pass `--cookiecutter` to use cookiecutter-pypackage instead; that path requires the
tripll **scaffold** extra (`uv sync --extra scaffold`).

### One emitter, two entry points

Greenfield calls the **same** spec/PRD/plan emitters as `tripll init`
(`tripll.onboard.emitters`). The only difference is project creation first.

### Safe re-runs

Same idempotence rules as brownfield:

```bash
tripll new my-project              # error if ./my-project exists without tripll.toml
cd my-project && tripll new .        # not supported — re-run init inside the repo instead
tripll init                          # reconcile docs/config inside an existing project
```

After the first scaffold, use `tripll init` inside the project to reconcile gaps.

## Credentials (R24)

tripll **never** stores provider API keys or tokens in `tripll.toml` or user config.
Run the login commands surfaced by `tripll doctor` when a provider shows `MISSING`.

## Related docs

- [`operator-runbook.md`](operator-runbook.md) — dispatch, HITL, git safety
- [`../wave-plan-template.md`](../wave-plan-template.md) — v3 plan format
- [`../decisions/003-plan-format-and-shape.md`](../decisions/003-plan-format-and-shape.md)
