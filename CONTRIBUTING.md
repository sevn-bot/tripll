# Contributing to tripll

Thanks for contributing! tripll follows the coding standards and tooling of the
[sevn.bot](https://github.com/sevn-bot/sevn.bot) project it was extracted from.

## Tech stack

- **Python 3.12+**, `src/` layout, built with **hatchling**.
- Package + dependency management with **[uv](https://docs.astral.sh/uv/)**.
- Logging with **loguru** (never the stdlib `logging` module).
- Optional observability via **Logfire/OpenTelemetry** (`obs` extra) — no-op without `LOGFIRE_TOKEN`.

## Setup

```bash
uv sync --extra dev --extra api --extra obs   # or: make setup
pre-commit install --install-hooks            # ruff + conventional-commit hooks
```

## Quality gate

Everything runs through **Make** (mirrors CI):

| Command | What it does |
|---------|--------------|
| `make lint` | `ruff check` + `ruff format --check` |
| `make typecheck` | `mypy --strict` on `src/tripll` |
| `make test` | `pytest` |
| `make check` | lint + typecheck + log-redact gate + test (**required gate**) |
| `make deps-audit` | OSV vulnerability scan of `uv.lock` (dev + api + obs extras) |
| `make ci` | `make check` + `make deps-audit` + `uv build` (full local mirror of GitHub Actions) |

Run `make check` (or `make ci`) before opening a PR.

## Style

- Line length 100; ruff is the formatter and linter (see `pyproject.toml`).
- Full type hints on public functions; `from __future__ import annotations` at module top.
- Module/function docstrings with `Exports:` and runnable `>>>` examples (sevn convention).
- `|` unions and lowercase generics (`list[str]`, `dict[str, Any]`).

## Commits

[Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/), enforced by the
`commit-msg` hook. Validate locally:

```bash
python scripts/check_conventional_commit.py --message "feat: add a thing"
```

## License

By contributing you agree your contributions are licensed under the [MIT License](LICENSE).
