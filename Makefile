.DEFAULT_GOAL := help

# tripll — standalone wave-plan execution pipeline (run from this directory).
# CI entry point: make check  (lint + typecheck + test); make ci adds a build.

UV ?= uv
# Clear any inherited VIRTUAL_ENV so uv uses this project's .venv (avoids mismatch warning).
UV_RUN ?= env -u VIRTUAL_ENV $(UV)
RUFF ?= $(UV_RUN) run ruff
MYPY ?= $(UV_RUN) run mypy

# pullfrog-py ref for local `make review` — pinned to the same SHA as
# .github/workflows/pullfrog.yml (override: TRIPLL_PULLFROG_PY_REF=main).
PULLFROG_PY_REF ?= $(if $(TRIPLL_PULLFROG_PY_REF),$(TRIPLL_PULLFROG_PY_REF),0d40626097fd92976425f7eacd2e213ee1f6d5d5)

# Default runs/ relative to this directory (override: TRIPLL_RUNS=… make …)
export TRIPLL_RUNS := $(abspath runs)
# Target git checkout that tripll orchestrates (the repo whose worktrees are managed).
# Standalone default: only export when the operator sets it; otherwise the runtime
# (tripll.repo_root.resolve_repo_root) walks up from CWD to find the .git root.
TRIPLL_REPO_ROOT ?=
ifneq ($(strip $(TRIPLL_REPO_ROOT)),)
export TRIPLL_REPO_ROOT
endif
# Stream engine progress to the terminal (VERBOSE=0 silences; DEBUG=1 dumps raw stream-json).
TRIPLL_VERBOSE ?= 1
export TRIPLL_VERBOSE
TRIPLL_CLI ?= $(UV_RUN) run tripll

INPUT_DIR ?= runs/input
# Backend selection — use PROVIDER= or BACKEND= (same thing).
# Portable (macOS BSD make + GNU make):
#   make resume-run RUN=<id> PROVIDER=cursor_local MODEL=auto
# GNU make only (pseudo-goals after the target):
#   make resume-run RUN=<id> --provider=cursor_local --model=auto
_PROVIDER_GOAL := $(filter --provider=%,$(MAKECMDGOALS))
_MODEL_GOAL := $(filter --model=%,$(MAKECMDGOALS))
_AGENT_GOAL := $(filter --agent=%,$(MAKECMDGOALS))
_FOLDER_GOAL := $(filter --folder=%,$(MAKECMDGOALS))
ifneq ($(_PROVIDER_GOAL),)
  PROVIDER := $(patsubst --provider=%,%,$(_PROVIDER_GOAL))
endif
ifneq ($(_MODEL_GOAL),)
  MODEL := $(patsubst --model=%,%,$(_MODEL_GOAL))
endif
ifneq ($(_AGENT_GOAL),)
  AGENT := $(patsubst --agent=%,%,$(_AGENT_GOAL))
endif
ifneq ($(_FOLDER_GOAL),)
  FOLDER := $(patsubst --folder=%,%,$(_FOLDER_GOAL))
endif
# Swallow pseudo-goals so make does not treat them as missing targets.
$(foreach g,$(_PROVIDER_GOAL) $(_MODEL_GOAL) $(_AGENT_GOAL) $(_FOLDER_GOAL),$(eval $(g):;@:))

PROVIDER ?=
BACKEND ?= $(if $(PROVIDER),$(PROVIDER),claude_code)
MODEL ?=
AGENT ?=

FOLDER ?= .sevn/turns

_TRIPLL_BACKEND_FLAGS := --backend $(BACKEND) \
	$(if $(MODEL),--model $(MODEL),) \
	$(if $(AGENT),--agent $(AGENT),)

# Resume without PROVIDER/MODEL uses dispatch-config.json from run start.
_TRIPLL_RESUME_FLAGS := \
	$(if $(PROVIDER),--backend $(PROVIDER),) \
	$(if $(MODEL),--model $(MODEL),) \
	$(if $(AGENT),--agent $(AGENT),)

PLANS_COMPOSE := docker-compose.agent-native-plans.yml
PLANS_ENV := .env.agent-native

.PHONY: help sync sync-api init tripll lint typecheck test check deps-audit log-redact-check pullfrog-ref-check review serve status-watch orchestrator-watch \
	plan-set dry-run-set run-set plan-input run-input status list-input list-all-runs \
	validate-set validate-input pre0-interview approve-run resume-run continue-run finish-pre0 delete-run reset-run \
	build-plan-from-errors dry-run-build-plan-from-errors seed-orchestrator-smoke-set smoke-orchestrator-w0 \
	plans-up plans-down plans-logs spec-check prd-check changelog-check changelog-eval docs-score bench

help: ## Show targets (default goal — use `make` or `make help`, not GNU `make --help`)
	@printf '\033[1mtripll\033[0m — operator targets (run from this directory)\n'
	@printf 'Use \033[1mmake\033[0m or \033[1mmake help\033[0m. (\033[33mmake --help\033[0m is GNU Make usage, not this list.)\n\n'
	@awk 'BEGIN {FS = ":.*##"} \
		/^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5); next } \
		/^[a-zA-Z0-9_.-]+:.*##/ { gsub(/^ /, "", $$2); printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2 }' \
		$(MAKEFILE_LIST)
	@printf '\nVariables: \033[33mSET\033[0m=<input-set>  \033[33mRUN\033[0m=<run-id>\n'
	@printf '  \033[33mPROVIDER\033[0m=claude_code|cursor_local|cursor_cloud  \033[33mMODEL\033[0m=auto|…  \033[33mAGENT\033[0m=wave-plan-executor\n'
	@printf '  Example: make continue-run RUN=<id> \033[33mPROVIDER\033[0m=cursor_local \033[33mMODEL\033[0m=auto\n'
	@printf '  (\033[33m--provider\033[0m= / \033[33m--model\033[0m= after target need GNU make / brew install make)\n'
	@printf '  \033[33mVERBOSE\033[0m=0|1  \033[33mDEBUG\033[0m=1  \033[33mARGS\033[0m=…\n'
	@printf '  \033[33mFOLDER\033[0m=<turn-bundles-dir>  (build-plan-from-errors / dry-run-build-plan-from-errors; default .sevn/turns)\n'

##@ Turn-bundle plans (W0 stub — driver in W5)

build-plan-from-errors: sync ## Walk turn bundles → wave plans from error turns (W5)
	@$(UV_RUN) run python -m tripll.build_plan_from_errors --folder "$(FOLDER)" $(_TRIPLL_BACKEND_FLAGS)

dry-run-build-plan-from-errors: sync ## Preview argv only — FOLDER=<dir> [PROVIDER=…] [MODEL=…] [AGENT=…]
	@$(UV_RUN) run python -m tripll.build_plan_from_errors --dry-run --folder "$(FOLDER)" $(_TRIPLL_BACKEND_FLAGS)

##@ Setup

sync: ## Install deps (tripll CLI in uv project env)
	$(UV_RUN) sync --extra dev --extra graph

sync-api: ## Install dev + api extras (required for make serve / API tests)
	$(UV_RUN) sync --extra dev --extra api

serve: sync-api ## Start FastAPI control-plane server (default localhost:8765)
	$(UV_RUN) run tripll serve

init: sync ## Create runs/{input,processing,processed,failed} layout
	$(TRIPLL_CLI) init

list-input: sync ## List wave sets waiting in runs/input/
	@echo "Sets in $(INPUT_DIR)/:"; \
	found=0; \
	for d in "$(INPUT_DIR)"/*/; do \
	  [ -d "$$d" ] || continue; \
	  found=1; echo "  $$(basename "$$d")"; \
	done; \
	[ "$$found" -eq 1 ] || echo "  (empty)"

##@ Input sets (runs/input/<SET>/)

validate-set: sync ## Validate v1 wave-plan(s) in one input set — SET=<name>
	@test -n "$(SET)" || (echo "Usage: make validate-set SET=<name>" >&2; exit 1)
	@test -d "$(INPUT_DIR)/$(SET)" || (echo "Not found: $(INPUT_DIR)/$(SET)/" >&2; exit 1)
	$(TRIPLL_CLI) validate "$(INPUT_DIR)/$(SET)"

validate-input: sync ## Validate v1 wave-plans in every runs/input/ subdirectory
	@set -e; \
	found=0; \
	for d in "$(INPUT_DIR)"/*/; do \
	  [ -d "$$d" ] || continue; \
	  found=1; \
	  echo ""; echo "=== validate: $$d ==="; \
	  $(TRIPLL_CLI) validate "$$d"; \
	done; \
	if [ "$$found" -eq 0 ]; then \
	  echo "No sets in $(INPUT_DIR)/" >&2; exit 1; \
	fi

plan-set: sync ## Parse graph + write deterministic parallel-wave.md — SET=<name>
	@test -n "$(SET)" || (echo "Usage: make plan-set SET=<name>   # runs/input/<name>/" >&2; exit 1)
	@test -d "$(INPUT_DIR)/$(SET)" || (echo "Not found: $(INPUT_DIR)/$(SET)/" >&2; exit 1)
	$(TRIPLL_CLI) validate "$(INPUT_DIR)/$(SET)"
	$(TRIPLL_CLI) plan "$(INPUT_DIR)/$(SET)" --dry-run --write-manifest

dry-run-set: sync ## Engine dry-run (argv/sample brief) — SET=<name> [PROVIDER=…] [MODEL=…]
	@test -n "$(SET)" || (echo "Usage: make dry-run-set SET=<name>" >&2; exit 1)
	@test -d "$(INPUT_DIR)/$(SET)" || (echo "Not found: $(INPUT_DIR)/$(SET)/" >&2; exit 1)
	$(TRIPLL_CLI) run "$(INPUT_DIR)/$(SET)" --dry-run $(_TRIPLL_BACKEND_FLAGS)

run-set: sync ## Start one run — SET=<name> [PROVIDER=…] [MODEL=…] [AGENT=…]
	@if [ -z "$(SET)" ] && [ -n "$(RUN)" ]; then \
	  echo "To continue a paused run use: make continue-run RUN=$(RUN)" >&2; \
	  echo "  (run-set starts a new run from runs/input/<SET>/)" >&2; \
	  exit 1; \
	fi
	@test -n "$(SET)" || (echo "Usage: make run-set SET=<name>" >&2; exit 1)
	@test -d "$(INPUT_DIR)/$(SET)" || (echo "Not found: $(INPUT_DIR)/$(SET)/" >&2; exit 1)
	$(TRIPLL_CLI) run "$(INPUT_DIR)/$(SET)" $(_TRIPLL_BACKEND_FLAGS) $(if $(WAIT_FOR_HITL),--wait-for-hitl,)

plan-input: sync ## Plan every subdirectory of runs/input/ (one by one; stops on error)
	@set -e; \
	found=0; \
	for d in "$(INPUT_DIR)"/*/; do \
	  [ -d "$$d" ] || continue; \
	  found=1; \
	  echo ""; echo "=== plan: $$d ==="; \
	  $(TRIPLL_CLI) plan "$$d" --dry-run; \
	done; \
	if [ "$$found" -eq 0 ]; then \
	  echo "No sets in $(INPUT_DIR)/ — drop a folder there first." >&2; exit 1; \
	fi

run-input: sync ## Run every subdirectory of runs/input/ sequentially [PROVIDER=…] [MODEL=…]
	@set -e; \
	found=0; \
	for d in "$(INPUT_DIR)"/*/; do \
	  [ -d "$$d" ] || continue; \
	  found=1; \
	  echo ""; echo "=== run: $$d ==="; \
	  $(TRIPLL_CLI) run "$$d" $(_TRIPLL_BACKEND_FLAGS); \
	done; \
	if [ "$$found" -eq 0 ]; then \
	  echo "No sets in $(INPUT_DIR)/ — drop a folder there first." >&2; exit 1; \
	fi

##@ Run control (runs/processing/<RUN>/)

status: sync ## Run status — optional RUN=<run-id> (omit to list all runs)
	$(TRIPLL_CLI) status $(RUN)

status-watch: sync ## Live-tail per-agent status — RUN=<run-id> (Ctrl-C to exit)
	@test -n "$(RUN)" || (echo "Usage: make status-watch RUN=<run-id>" >&2; exit 1)
	$(TRIPLL_CLI) status --watch "$(RUN)"

orchestrator-watch: sync ## Tail orchestrator-status.md — RUN=<run-id> (Ctrl-C to exit)
	@test -n "$(RUN)" || (echo "Usage: make orchestrator-watch RUN=<run-id>" >&2; exit 1)
	@run_dir=""; \
	for bucket in processing processed failed; do \
	  candidate="$(TRIPLL_RUNS)/$$bucket/$(RUN)"; \
	  if [ -f "$$candidate/orchestrator-status.md" ]; then run_dir="$$candidate"; break; fi; \
	done; \
	if [ -z "$$run_dir" ]; then \
	  echo "No orchestrator-status.md for RUN=$(RUN)" >&2; exit 1; \
	fi; \
	echo "Tailing $$run_dir/orchestrator-status.md (Ctrl-C to exit)"; \
	tail -f "$$run_dir/orchestrator-status.md"

list-all-runs: sync ## List pending input sets + all runs (processing/processed/failed)
	$(TRIPLL_CLI) list-runs

pre0-interview: sync ## Interactive Pre-0 decisions (multiple choice + notes) — RUN=<run-id>
	@test -n "$(RUN)" || (echo "Usage: make pre0-interview RUN=<run-id>" >&2; exit 1)
	$(TRIPLL_CLI) pre0-interview "$(RUN)"

approve-run: sync ## Mark Pre-0 approved after decisions — RUN=<run-id>
	@test -n "$(RUN)" || (echo "Usage: make approve-run RUN=<run-id>" >&2; exit 1)
	$(TRIPLL_CLI) approve "$(RUN)"

resume-run: sync ## Resume run — RUN=<run-id> [PROVIDER=…] [MODEL=…] (reactivates failed/)
	@test -n "$(RUN)" || (echo "Usage: make resume-run RUN=<run-id>" >&2; exit 1)
	$(TRIPLL_CLI) resume "$(RUN)" $(_TRIPLL_RESUME_FLAGS) $(if $(WAIT_FOR_HITL),--wait-for-hitl,)

continue-run: approve-run resume-run ## Approve Pre-0 + resume — RUN=<run-id> [PROVIDER=…] [MODEL=…]

finish-pre0: pre0-interview continue-run ## Interview + approve + resume — RUN=<run-id> [PROVIDER=…] [MODEL=…]

delete-run: sync ## Delete a run directory — RUN=<run-id> [YES=1 to skip prompt]
	@test -n "$(RUN)" || (echo "Usage: make delete-run RUN=<run-id> [YES=1]" >&2; exit 1)
	@if [ "$(YES)" = "1" ]; then \
	  $(TRIPLL_CLI) delete-run "$(RUN)" --yes; \
	else \
	  $(TRIPLL_CLI) delete-run "$(RUN)"; \
	fi

reset-run: sync ## Restore plan files to input/ and delete run — RUN=<run-id>
	@test -n "$(RUN)" || (echo "Usage: make reset-run RUN=<run-id>" >&2; exit 1)
	$(TRIPLL_CLI) reset-run "$(RUN)"

seed-orchestrator-smoke-set: sync ## Copy W0 example set → runs/input/orchestrator-mode-smoke/
	@mkdir -p "$(INPUT_DIR)/orchestrator-mode-smoke"
	@cp docs/examples/orchestrator-mode-input-set/*.md "$(INPUT_DIR)/orchestrator-mode-smoke/"
	@echo "Installed: $(INPUT_DIR)/orchestrator-mode-smoke/ (see docs/examples/orchestrator-mode-input-set/README.md)"

smoke-orchestrator-w0: sync ## W0 orchestrator smoke — validate + plan + pytest (Final.4)
	@bash scripts/smoke-orchestrator-w0.sh

##@ Agent-Native Plans (Docker sidecar, :3000)

plans-up: ## Start local Agent-Native Plans (Docker, :3000)
	@test -f "$(PLANS_ENV)" || ( \
		echo "Missing $(PLANS_ENV). Copy .env.agent-native.example and fill REPLACE_* secrets:" >&2; \
		echo "  cp .env.agent-native.example $(PLANS_ENV)" >&2; \
		echo "  openssl rand -hex 32   # repeat for each REPLACE_* secret" >&2; \
		exit 1 \
	)
	docker compose -f "$(PLANS_COMPOSE)" up -d --build

plans-down: ## Stop Plans container
	docker compose -f "$(PLANS_COMPOSE)" down

plans-logs: ## Tail Plans container logs
	docker compose -f "$(PLANS_COMPOSE)" logs -f

##@ Advanced

tripll: sync ## CLI passthrough — ARGS='plan runs/input/<set> --dry-run' | 'run …'
	@test -n "$(ARGS)" || (echo "Usage: make tripll ARGS='<subcommand> …'" >&2; exit 1)
	$(TRIPLL_CLI) $(ARGS)

##@ Quality gate

lint: sync ## Ruff check + format check
	$(RUFF) check --config pyproject.toml src tests
	$(RUFF) format --check --config pyproject.toml src tests

typecheck: sync ## mypy strict for tripll
	$(MYPY) --config-file pyproject.toml src/tripll

# Tier gating (W1.16): tier2 needs RUN_LIVE=1; tier4 never blocks make test.
PYTEST_TIER_EXPR = not tier4
ifndef RUN_LIVE
PYTEST_TIER_EXPR := $(PYTEST_TIER_EXPR) and not tier2
endif

test: ## pytest
	$(UV_RUN) run --extra dev --extra api --extra obs pytest tests -v --tb=short -m "$(PYTEST_TIER_EXPR)"

bench: sync ## Replay sealed brief-packing benchmark (tier 2 — minutes, not seconds)
	$(TRIPLL_CLI) bench run

log-redact-check: sync ## Validate log-hide-keys.toml + redaction unit tests
	@test -f config/log-hide-keys.toml || (echo "Missing config/log-hide-keys.toml" >&2; exit 1)
	$(UV_RUN) run --extra dev pytest tests/test_log_redact.py -v --tb=short

deps-audit: sync ## OSV vulnerability scan of uv.lock (dev+api+obs extras; fails on known CVEs)
	bash scripts/deps_audit.sh

check: lint typecheck log-redact-check pullfrog-ref-check about-site-check test ## Lint + typecheck + log redact + pullfrog pin + about-site drift + test (required gate)

pullfrog-ref-check: sync ## Fail when pullfrog-py pin drifts between pullfrog.yml and PULLFROG_PY_REF
	$(UV_RUN) run --extra dev python scripts/check_pullfrog_ref_parity.py

review: ## Advisory offline review vs origin/main via pullfrog-py (needs CLAUDE_CODE_OAUTH_TOKEN in `.env`)
	@set -a; \
	if [ -f .env ]; then . ./.env; fi; \
	set +a; \
	if [ -z "$${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && [ -z "$${ANTHROPIC_API_KEY:-}" ]; then \
		printf 'Neither CLAUDE_CODE_OAUTH_TOKEN nor ANTHROPIC_API_KEY set — add one to `.env`. Advisory review skipped.\n' >&2; \
		exit 0; \
	fi; \
	base="$${TRIPLL_CI_BASE:-origin/main}"; \
	echo "Running pullfrog-py diff-review (base=$$base, ref=$(PULLFROG_PY_REF))…"; \
	$(UV) tool run --python 3.14 --from git+https://github.com/alexhawat/pullfrog-py@$(PULLFROG_PY_REF) \
		pfpy diff-review --base "$$base"

setup: ## Fresh checkout: sync deps + install git hooks (CI bootstrap entry point)
	$(UV_RUN) sync --extra dev --extra api --extra obs
	@command -v pre-commit >/dev/null 2>&1 && pre-commit install --install-hooks || \
		$(UV_RUN) run --extra dev pre-commit install --install-hooks || true

build: ## Build wheel + sdist into dist/
	$(UV) build

ci: check deps-audit build ## Full local gate mirrored by GitHub Actions (check + deps-audit + build)

about-site: ## Regenerate the about-tripll/ help site from _sources + _templates
	$(UV_RUN) run --extra dev python scripts/build_about_site.py

about-site-check: ## Fail if about-tripll/ HTML is stale (CI drift gate)
	$(UV_RUN) run --extra dev python scripts/build_about_site.py --check

OUT ?= scaffold-out
scaffold-package: ## Scaffold + normalize a new package (NAME=<project> [OUT=<dir>]) via cookiecutter
	@test -n "$(NAME)" || { echo "usage: make scaffold-package NAME=<project-name> [OUT=<dir>]"; exit 1; }
	$(UV_RUN) run --extra scaffold python -c "from tripll.scaffold import scaffold_package; print('scaffolded:', scaffold_package(project_name='$(NAME)', output_dir='$(OUT)'))"

##@ Doc gates (absorbed spec-kit-wave / skw)

SPEC_DIR ?= docs
PRD_DIR ?= docs/prd
KIND ?= spec
DOCS_DIR ?= $(if $(filter prd,$(KIND)),$(PRD_DIR),$(SPEC_DIR))
REPO_ROOT ?= $(CURDIR)

spec-check: sync ## Validate+score specs in SPEC_DIR (default docs/)
	$(TRIPLL_CLI) spec validate "$(SPEC_DIR)" --repo-root "$(REPO_ROOT)"

prd-check: sync ## Validate+score PRDs in PRD_DIR (SCORE=1 for score-only gate)
	@if [ "$(SCORE)" = "1" ]; then \
		$(TRIPLL_CLI) prd score "$(PRD_DIR)" --repo-root "$(REPO_ROOT)"; \
	else \
		$(TRIPLL_CLI) prd validate "$(PRD_DIR)" --repo-root "$(REPO_ROOT)"; \
	fi

docs-score: sync ## Score docs in DOCS_DIR for KIND=spec|prd
	$(TRIPLL_CLI) doc-score --kind $(KIND) --dir "$(DOCS_DIR)" --repo-root "$(REPO_ROOT)"

changelog-check: sync ## Deterministic CHANGELOG.md gate (BASE=origin/main)
	$(TRIPLL_CLI) changelog check --repo-root "$(REPO_ROOT)" --base "$(or $(BASE),origin/main)"

changelog-eval: sync ## Advisory LLM double-score for Unreleased entries (not in CI)
	$(TRIPLL_CLI) changelog eval --repo-root "$(REPO_ROOT)" --base "$(or $(BASE),origin/main)"

SKW_RENDER := $(UV_RUN) run python -m tripll.skw.render --kit-root src/tripll/skw

install-skills: ## Symlink skw kit skills into .cursor/skills and .claude/skills
	@set -e; \
	for skill in src/tripll/skw/skills/*/; do \
		name=$$(basename "$$skill"); \
		mkdir -p .cursor/skills .claude/skills; \
		ln -sfn "$$(pwd)/$$skill" ".cursor/skills/$$name"; \
		ln -sfn "$$(pwd)/$$skill" ".claude/skills/$$name"; \
	done

validate: sync ## Validate a wave plan — WAVE=<path>
	@test -n "$(WAVE)" || { echo "usage: make validate WAVE=<path>"; exit 1; }
	$(TRIPLL_CLI) validate-plan "$(WAVE)"

validate-selftest: sync ## Validate skw example wave plan (kit self-test)
	$(UV_RUN) run python -m tripll.skw.validate src/tripll/skw/waves/example-wave-plan.md

specify-run: sync ## Render specify prompt — SLUG= TITLE= [CONTEXT=] [PATHS=]
	@test -n "$(SLUG)" && test -n "$(TITLE)" || { echo "usage: make specify-run SLUG= TITLE= [CONTEXT=] [PATHS=]"; exit 1; }
	$(SKW_RENDER) --stage specify --slug "$(SLUG)" --title "$(TITLE)" $(if $(CONTEXT),--context "$(CONTEXT)",) $(if $(PATHS),--paths "$(PATHS)",)

wave-generator-run: sync ## Render wave-generator prompt — SLUG= TITLE= [CONTEXT=] [PATHS=]
	@test -n "$(SLUG)" && test -n "$(TITLE)" || { echo "usage: make wave-generator-run SLUG= TITLE= [CONTEXT=] [PATHS=]"; exit 1; }
	$(SKW_RENDER) --stage wave-generator --slug "$(SLUG)" --title "$(TITLE)" $(if $(CONTEXT),--context "$(CONTEXT)",) $(if $(PATHS),--paths "$(PATHS)",)

github-issue-triage: sync ## Fetch open issues JSON (use ISSUE= or QUEUE=1 with github-issue-triage-run)
	python3 src/tripll/skw/skills/github-issue-triage/scripts/fetch_open_issues.py --limit 100

github-issue-triage-run: sync ## Render github-issue-triage prompt — ISSUE=<n> or QUEUE=1 [CONTEXT=] [PATHS=]
	@test -n "$(ISSUE)" || test "$(QUEUE)" = "1" || { echo "usage: make github-issue-triage-run ISSUE=<n> or QUEUE=1"; exit 1; }
	$(SKW_RENDER) --stage github-issue-triage $(if $(ISSUE),--issue "$(ISSUE)",) $(if $(filter 1,$(QUEUE)),--queue,) $(if $(CONTEXT),--context "$(CONTEXT)",) $(if $(PATHS),--paths "$(PATHS)",)

verifier-setup-run: sync ## Render verifier-setup prompt [CONTEXT=] [PATHS=]
	$(SKW_RENDER) --stage verifier-setup $(if $(CONTEXT),--context "$(CONTEXT)",) $(if $(PATHS),--paths "$(PATHS)",)
