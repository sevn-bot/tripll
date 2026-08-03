"""mergeCraft review integration — config, scaffold, CLI runner, mode dispatch.

Exports:
    ReviewCiConfig — push/shell/status_checks/model for CI Action inputs.
    ReviewConfig — provider, ref, posture, and CI block.
    POSTURE_PRESETS — review_only | fix | full → push/shell defaults.
    review_config_from_raw — coerce merged TOML ``[review]`` table.
    resolve_mergecraft_ref — SHA/ref for ``uv tool run`` / Makefile override.
    scaffold_mergecraft — write ``.mergecraft/`` + optional workflow.
    run_mergecraft — invoke external ``mergecraft`` via ``uv tool run``.
    dispatch_mode — ``gh workflow run mergecraft.yml`` when posture allows.
    load_mergecraft_findings_json — parse ``diff-review --json`` payloads.
    normalize_mergecraft_findings — map mergeCraft findings to tripll schema.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path  # noqa: TC003 — used at runtime in scaffold/dispatch
from typing import Any, Literal, cast

from loguru import logger

from tripll.review.findings_json import (
    MERGECRAFT_FINDING_REQUIRED_KEYS,
    MergecraftFindingsPayloadError,
    load_mergecraft_findings_json,
    normalize_mergecraft_finding,
    normalize_mergecraft_findings,
)

Posture = Literal["review_only", "fix", "full"]
Permission = Literal["disabled", "restricted", "enabled"]

DEFAULT_MERGECRAFT_SHA = "f369164c609aa6ffb4149b0248f72f6a3e10b0a6"
DEFAULT_MERGECRAFT_REF_LABEL = "main"
WORKFLOW_NAME = "mergecraft.yml"

POSTURE_PRESETS: dict[Posture, dict[str, Permission]] = {
    "review_only": {"push": "disabled", "shell": "disabled"},
    "fix": {"push": "restricted", "shell": "restricted"},
    "full": {"push": "restricted", "shell": "restricted"},
}

__all__ = [
    "DEFAULT_MERGECRAFT_SHA",
    "MERGECRAFT_FINDING_REQUIRED_KEYS",
    "POSTURE_PRESETS",
    "MergecraftFindingsPayloadError",
    "ReviewCiConfig",
    "ReviewConfig",
    "dispatch_mode",
    "load_mergecraft_findings_json",
    "normalize_mergecraft_finding",
    "normalize_mergecraft_findings",
    "resolve_mergecraft_ref",
    "review_config_from_raw",
    "run_mergecraft",
    "scaffold_mergecraft",
]


@dataclass(frozen=True, slots=True)
class ReviewCiConfig:
    """CI Action inputs for mergeCraft.

    Args:
        push (Permission): Git push permission for the Action.
        shell (Permission): Shell permission for the Action.
        status_checks (bool): Post ``mergecraft-approval`` check-runs.
        model (str): Model slug for the Action.
    """

    push: Permission = "disabled"
    shell: Permission = "disabled"
    status_checks: bool = True
    model: str = "anthropic/claude-sonnet"


@dataclass(frozen=True, slots=True)
class ReviewConfig:
    """Resolved ``[review]`` block from ``tripll.toml``.

    Args:
        provider (str): Review provider id (only ``mergecraft`` today).
        ref (str): mergeCraft git ref or SHA (label or commit).
        posture (Posture): Capability preset controlling push/shell.
        ci (ReviewCiConfig): Explicit CI overrides (win over posture).
        workflow (str): Workflow file name under ``.github/workflows/``.
    """

    provider: str = "mergecraft"
    ref: str = DEFAULT_MERGECRAFT_REF_LABEL
    posture: Posture = "review_only"
    ci: ReviewCiConfig = field(default_factory=ReviewCiConfig)
    workflow: str = WORKFLOW_NAME

    def effective_ci(self) -> ReviewCiConfig:
        """Return CI config with posture defaults applied.

        Explicit ``[review.ci]`` push/shell values always win; when the
        ReviewCiConfig was built via :func:`review_config_from_raw`, those
        fields already incorporate the posture preset.

        Returns:
            ReviewCiConfig: Resolved push/shell/status_checks/model.
        """
        return self.ci

    def allows_mode_dispatch(self) -> bool:
        """Return True when Fix / AddressReviews workflow_dispatch is allowed."""
        return self.posture != "review_only"


def review_config_from_raw(raw: dict[str, Any] | None) -> ReviewConfig:
    """Coerce a merged TOML ``[review]`` table into :class:`ReviewConfig`.

    Args:
        raw (dict[str, Any] | None): ``cfg.raw.get("review")`` or None.

    Returns:
        ReviewConfig: Defaults when *raw* is missing or empty.
    """
    if not isinstance(raw, dict):
        return ReviewConfig()
    posture_raw = str(raw.get("posture") or "review_only").strip().lower()
    if posture_raw in ("review_only", "fix", "full"):
        posture = cast("Posture", posture_raw)
    else:
        posture = "review_only"
    ci_raw_obj = raw.get("ci")
    ci_raw: dict[str, Any] = ci_raw_obj if isinstance(ci_raw_obj, dict) else {}
    preset = POSTURE_PRESETS[posture]

    def _perm(key: str) -> Permission:
        candidate = ci_raw.get(key) or preset[key]
        val = str(candidate).strip().lower()
        allowed: dict[str, Permission] = {
            "disabled": "disabled",
            "restricted": "restricted",
            "enabled": "enabled",
        }
        return allowed.get(val, preset[key])

    status = ci_raw.get("status_checks", True)
    return ReviewConfig(
        provider=str(raw.get("provider") or "mergecraft"),
        ref=str(raw.get("ref") or DEFAULT_MERGECRAFT_REF_LABEL),
        posture=posture,
        ci=ReviewCiConfig(
            push=_perm("push"),
            shell=_perm("shell"),
            status_checks=bool(status),
            model=str(ci_raw.get("model") or "anthropic/claude-sonnet"),
        ),
        workflow=str(raw.get("workflow") or WORKFLOW_NAME),
    )


def resolve_mergecraft_ref(cfg: ReviewConfig | None = None) -> str:
    """Return the mergeCraft git ref for ``uv tool run``.

    Precedence: ``TRIPLL_MERGECRAFT_REF`` → config ``ref`` → pinned SHA.

    Args:
        cfg (ReviewConfig | None): Optional review config.

    Returns:
        str: Git ref or SHA.
    """
    env = os.environ.get("TRIPLL_MERGECRAFT_REF", "").strip()
    if env:
        return env
    if cfg is not None and cfg.ref and cfg.ref != DEFAULT_MERGECRAFT_REF_LABEL:
        return cfg.ref
    if cfg is not None and cfg.ref == DEFAULT_MERGECRAFT_REF_LABEL:
        return DEFAULT_MERGECRAFT_SHA
    return DEFAULT_MERGECRAFT_SHA


def _workflow_yaml(*, push: Permission, shell: Permission, model: str) -> str:
    contents_perm = "write" if push != "disabled" else "read"
    return f"""\
# mergeCraft PR review (BYOK; https://github.com/alexhawat/mergeCraft).
# Scaffolded by `tripll init` / `tripll review init`. Widen posture via tripll.toml [review].
name: mergeCraft

on:
  pull_request:
    branches: [main]
    types: [opened, synchronize, reopened, ready_for_review]
  workflow_dispatch:
    inputs:
      prompt:
        description: Prompt for the agent (workflow_dispatch only)
        required: false
        type: string

permissions:
  contents: {contents_perm}
  pull-requests: write
  issues: write
  checks: write
  statuses: write
  id-token: write

concurrency:
  group: mergecraft-${{{{ github.workflow }}}}-${{{{ github.ref }}}}
  cancel-in-progress: true

jobs:
  review:
    name: mergeCraft review
    if: github.event_name == 'workflow_dispatch' || github.event.pull_request.draft == false
    runs-on: ubuntu-latest
    timeout-minutes: 30
    env:
      HAS_AUTH: ${{{{ secrets.CLAUDE_CODE_OAUTH_TOKEN != '' || secrets.ANTHROPIC_API_KEY != '' }}}}

    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
          persist-credentials: false

      - name: Skip when auth is not configured
        if: env.HAS_AUTH != 'true'
        run: |
          echo "::notice title=mergeCraft skipped::Configure CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY."

      - name: mergeCraft PR review
        if: env.HAS_AUTH == 'true'
        id: mergecraft
        continue-on-error: true
        uses: alexhawat/mergeCraft@{DEFAULT_MERGECRAFT_SHA} # {DEFAULT_MERGECRAFT_REF_LABEL}
        with:
          prompt: >-
            ${{{{ (github.event_name == 'pull_request' && format('Review pull request #{{0}}. Focus on correctness, security, regressions, missing tests, and maintainability.', github.event.pull_request.number))
                || (github.event_name == 'workflow_dispatch' && inputs.prompt != '' && inputs.prompt)
                || 'Review the current pull request.' }}}}
          model: {model}
          push: {push}
          shell: {shell}
          status_checks: enabled
        env:
          CLAUDE_CODE_OAUTH_TOKEN: ${{{{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}}}
          ANTHROPIC_API_KEY: ${{{{ secrets.ANTHROPIC_API_KEY }}}}
"""


_CONFIG_YAML = """\
# mergeCraft per-repo settings (https://github.com/alexhawat/mergeCraft).
# Workflow inputs for model/push/shell/status_checks win over this file.
# Sibling learnings.md holds withdrawn findings (D13 / tripll findings triage).

staticChecks:
  - name: lint
    command: make lint
  - name: typecheck
    command: make typecheck
  - name: check
    command: make check
"""


def scaffold_mergecraft(
    root: Path,
    *,
    review: ReviewConfig | None = None,
    force: bool = False,
    write_workflow: bool = True,
) -> list[str]:
    """Write ``.mergecraft/config.yaml``, learnings template, optional workflow.

    Args:
        root (Path): Repository root.
        review (ReviewConfig | None): Posture / CI settings for the workflow.
        force (bool): Overwrite existing files when True.
        write_workflow (bool): Also emit ``.github/workflows/mergecraft.yml``.

    Returns:
        list[str]: Operator-facing paths written or skipped.
    """
    from tripll.github.learnings import ensure_learnings_template

    cfg = review or ReviewConfig()
    ci = cfg.effective_ci()
    messages: list[str] = []
    mc_dir = root / ".mergecraft"
    mc_dir.mkdir(parents=True, exist_ok=True)

    config_path = mc_dir / "config.yaml"
    if force or not config_path.exists():
        config_path.write_text(_CONFIG_YAML, encoding="utf-8")
        messages.append(f"Wrote {config_path.relative_to(root)}")
    else:
        messages.append(f"Kept {config_path.relative_to(root)}")

    learnings = ensure_learnings_template(mc_dir / "learnings.md", force=force)
    if learnings is not None:
        messages.append(f"Wrote {learnings.relative_to(root)}")

    if write_workflow:
        wf_dir = root / ".github" / "workflows"
        wf_dir.mkdir(parents=True, exist_ok=True)
        wf_path = wf_dir / cfg.workflow
        if force or not wf_path.exists():
            wf_path.write_text(
                _workflow_yaml(push=ci.push, shell=ci.shell, model=ci.model),
                encoding="utf-8",
            )
            messages.append(f"Wrote {wf_path.relative_to(root)} (posture={cfg.posture})")
        else:
            messages.append(f"Kept {wf_path.relative_to(root)}")
    return messages


def run_mergecraft(
    args: list[str],
    *,
    ref: str | None = None,
    cwd: Path | None = None,
) -> int:
    """Run external ``mergecraft`` via ``uv tool run`` (no package dependency).

    Args:
        args (list[str]): Arguments after the ``mergecraft`` binary name.
        ref (str | None): Git ref/SHA; defaults to :func:`resolve_mergecraft_ref`.
        cwd (Path | None): Working directory for the subprocess.

    Returns:
        int: Process exit code.
    """
    uv = shutil.which("uv")
    if uv is None:
        logger.error("uv not found on PATH — required to run mergeCraft")
        return 1
    pin = ref or resolve_mergecraft_ref()
    cmd = [
        uv,
        "tool",
        "run",
        "--python",
        "3.14",
        "--from",
        f"git+https://github.com/alexhawat/mergeCraft@{pin}",
        "mergecraft",
        *args,
    ]
    logger.info("Running {}", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=False)
    return int(proc.returncode)


def dispatch_mode(
    *,
    pr: int,
    mode: str,
    prompt: str,
    workflow: str = WORKFLOW_NAME,
    review: ReviewConfig | None = None,
    dry_run: bool = False,
    receipt_path: Path | None = None,
) -> dict[str, Any]:
    """Trigger ``gh workflow run`` for a mergeCraft mode when posture allows.

    No-ops with ``skipped: true`` when ``posture == review_only`` (default).

    Args:
        pr (int): Pull request number (included in the prompt).
        mode (str): mergeCraft mode name (AddressReviews, Fix, …).
        prompt (str): Agent prompt body.
        workflow (str): Workflow file name.
        review (ReviewConfig | None): Posture gate; loaded defaults when None.
        dry_run (bool): When True, do not call ``gh``.
        receipt_path (Path | None): Optional JSON receipt path (ADR 004).

    Returns:
        dict[str, Any]: Result with ``ok``, ``skipped``, and optional ``error``.
    """
    cfg = review or ReviewConfig()
    result: dict[str, Any] = {
        "ok": True,
        "skipped": False,
        "mode": mode,
        "pr": pr,
        "workflow": workflow,
    }
    if not cfg.allows_mode_dispatch():
        result["skipped"] = True
        result["reason"] = "posture=review_only — set [review].posture to fix|full in tripll.toml"
        logger.info("mergeCraft dispatch skipped: {}", result["reason"])
        return result

    full_prompt = f"Mode: {mode}. PR #{pr}.\n\n{prompt}"
    if dry_run:
        result["dry_run"] = True
        result["prompt"] = full_prompt
        return result

    gh = shutil.which("gh")
    if gh is None:
        result["ok"] = False
        result["error"] = "gh not found on PATH"
        return result

    cmd = [
        gh,
        "workflow",
        "run",
        workflow,
        "-f",
        f"prompt={full_prompt}",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    result["returncode"] = proc.returncode
    if proc.returncode != 0:
        result["ok"] = False
        result["error"] = (proc.stderr or proc.stdout or "gh workflow run failed").strip()
    if receipt_path is not None:
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result
