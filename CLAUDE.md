# Agent notes — tripll

Instructions for AI assistants and contributors editing the **tripll** checkout. tripll is a
headless, parallel **wave-plan execution pipeline**.

## Project context

tripll parses a set of wave-plan files into a **RunGraph** (lanes, batches, Pre-0 human gates,
content-window seams), dispatches each wave to an agent backend (`claude_code`, `cursor_local`,
`cursor_cloud`) in dependency order, enforces a Pre-0 human gate, retries failures, and can
integrate batches on a branch. Stack: **Python 3.12+**, **`src/tripll/`** (hatchling / uv),
loguru logging, optional Logfire observability, FastAPI control plane + dashboard (`api` extra).

## Where to read

| Need | Start here |
|------|------------|
| Architecture / graph model | [`docs/design-note.md`](docs/design-note.md) |
| Control plane / dashboard | [`docs/control-plane-design.md`](docs/control-plane-design.md) |
| Operations | [`docs/runbooks/operator-runbook.md`](docs/runbooks/operator-runbook.md) |
| Wave-plan format | [`docs/wave-plan-template.md`](docs/wave-plan-template.md) · [`docs/decisions/003-plan-format-and-shape.md`](docs/decisions/003-plan-format-and-shape.md) |
| Design decisions (ADRs) | [`docs/decisions/`](docs/decisions/) |
| Agent roles (wave executor, test-creator, …) | [`docs/agents/`](docs/agents/) · [`src/tripll/skw/agents/`](src/tripll/skw/agents/) |
| Coding standards (normative) | [`about-tripll/_standards/coding-standards.md`](about-tripll/_standards/coding-standards.md) |
| Public docs site | [`about-tripll/`](about-tripll/) — built via `make about-site` |

## Commands

Use **Make** for every recurring command — run **`make help`** for the full list.

| Target | When |
|--------|------|
| **`make setup`** | Fresh checkout: `uv sync` (dev/api/obs) + git hooks |
| **`make check`** | Required gate: lint + typecheck + log-redact gate + test |
| **`make ci`** | `make check` + `uv build` (mirrors GitHub Actions) |
| **`make lint`** / **`make typecheck`** | After Python edits on touched paths |
| **`make test`** | `pytest tests` |
| **`make about-site`** | Regenerate the `about-tripll/` HTML after editing `_sources/`/`_templates/` |

Do **not** document or rely on raw `uv run pytest`/`ruff`/`mypy` in recurring flows — those run
**only** through Makefile targets. Always go through **`uv`** (never raw pip/pytest/ruff/mypy).

## Python changes

Follow [`about-tripll/_standards/coding-standards.md`](about-tripll/_standards/coding-standards.md):
src layout, `from __future__ import annotations`, full type hints + docstrings (`Exports:` /
`Args:` / `Returns:` / `Examples:`), `|` unions, lowercase generics, line length 100, **loguru
only** (never stdlib `logging`). Before finishing: **`make lint`** and **`make typecheck`** (or
**`make check`**) on touched paths.

## Observability

Optional Logfire/OTel via the `obs` extra and `tripll.obs.configure_observability()` (wired into
the CLI). It is a **no-op** without `LOGFIRE_TOKEN` and must never break the CLI.

## External dependencies

tripll is standalone — never add a hard dependency on another product's package. The one optional
integration is the `cursor_cloud` adapter, which probes for `sevn.evolution.router` via
`importlib.util.find_spec` under the `cloud` extra and degrades gracefully when that package is
absent. The target repo tripll orchestrates is resolved from `TRIPLL_REPO_ROOT` or the CWD git
root (`tripll.repo_root.resolve_repo_root`).

## Git safety

**Never** run `git clean` with **`-x`/`-X`** — those delete gitignored local trees (`runs/`,
`ignorelocal/`, `evidence/`, `.env`). Use `git restore` on tracked paths only. See
[`docs/runbooks/operator-runbook.md` — Git safety](docs/runbooks/operator-runbook.md#git-safety-git-clean-guard).

## Git & commits

[Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/), enforced by the
`commit-msg` hook (`scripts/check_conventional_commit.py`). Load **`.claude/skills/conventional-commit`**
when drafting commits.

- **Do not commit** unless the user explicitly asks.
- Do **not** use **`--no-verify`** unless the user explicitly allows it.
- Validate subjects: `python scripts/check_conventional_commit.py --message 'feat: …'`.
