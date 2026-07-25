"""tripll.brief — dispatch-brief rendering for wave-runner sub-agents.

Renders both the **JSON dispatch brief** (design-note.md §2 schema) and the
**human prompt** (the wave-runner "Quick start template") from a
:class:`~tripll.graph.WaveNode`.

Exports:
    orchestrator_directives — orchestrator-mode agent directives (D7).
    extract_wave_summary — first H2 block or 2000 chars from agent result (D6).
    render_json_brief — build the JSON dispatch-brief dict for a node.
    render_human_brief — build the wave-runner Quick-start text for a node.
    render_dispatch_prompt — human-readable agent prompt from a brief dict.
    write_brief — write a JSON brief to disk and return its path.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from tripll.serve.handoff import HANDOFF_GOVERNING_RULE, format_handoff_block
from tripll.workspace import compute_workspace_scope

if TYPE_CHECKING:
    from pathlib import Path

    from tripll.graph import OrchestratorConfig, WaveNode
    from tripll.graphstore import GraphStore

BRIEF_VERSION = "1.1"

GREP_EXPLORATION_DIRECTIVE = (
    "Stay within workspace_scope paths; no repo-wide grep, graphify, or architecture "
    "tours unless blocked."
)

GRAPH_PACKED_DIRECTIVE = (
    "Use the packed subgraph section below for context; do not run repo-wide grep, "
    "graphify, or architecture tours unless the packed context is insufficient."
)

AGENT_DIRECTIVES: list[str] = [
    "Leave changes staged; do not commit.",
    "Do not run full make ci mid-wave — use make ci-affected (make ci-changed for Python-only).",
    "Run make ci once at wave boundary / before merge.",
    "Do not edit the ci: Makefile target.",
    "Do not edit forbidden_paths listed above.",
    "No src/sevn/ edits outside owned_paths.",
    "Read only the staged wave slice under plan/tripll/ for this wave.",
    GRAPH_PACKED_DIRECTIVE,
    "Run shell/make via the Shell tool in-process; do not spawn Task/shell subagents "
    "(Cursor CLI rejects shell subagent_type).",
]


def orchestrator_directives(
    config: OrchestratorConfig,
    wave_id: str,
    *,
    commit_subject: str = "",
) -> list[str]:
    """Return orchestrator-mode agent directives replacing ``AGENT_DIRECTIVES`` (D7).

    Args:
        config (OrchestratorConfig): Active orchestrator settings.
        wave_id (str): Wave id for commit-subject lookup.
        commit_subject (str): Override commit subject when non-empty.

    Returns:
        list[str]: Directive lines for the dispatch brief.

    Examples:
        >>> from tripll.graph import OrchestratorConfig
        >>> d = orchestrator_directives(OrchestratorConfig(True, "p.md"), "W2")
        >>> any("integration branch" in x for x in d)
        True
    """
    subject = commit_subject or config.commit_subjects.get(wave_id, f"feat(tripll): {wave_id}")
    verify = f"SEVN_CI_BASE={config.ci_base} make {config.verify_target}"
    branch = config.feature_branch or "(feature branch)"
    completion = (
        f"## Wave {wave_id} complete\n"
        f"**Commit:** {subject}\n"
        "### Files touched\n…\n"
        "### Verification\n"
        f"{verify} + make -C wave-orchestrator check"
    )
    return [
        f"Work on integration branch `{branch}` only; stay within wave-runner scope.",
        f"After verify passes: commit with subject `{subject}` and push to origin.",
        f"Validate subject: `make commit-msg-check MSG='{subject}'` from repo root.",
        f"Run `{verify}` from repo root before commit; then `make -C wave-orchestrator check`.",
        "Do not use `--no-verify` on commits.",
        "Do not run full `make ci` mid-wave.",
        "Do not edit forbidden_paths listed above.",
        "Read only the staged wave slice under plan/tripll/ for this wave.",
        f"Return completion markdown:\n{completion}",
    ]


def extract_wave_summary(result_text: str, *, limit: int = 2000) -> str:
    """Extract wave-complete summary from agent *result_text* (D6).

    Args:
        result_text (str): Raw agent completion markdown.
        limit (int): Maximum characters to return.

    Returns:
        str: First ``##`` section or truncated body; empty when *result_text* is blank.

    Examples:
        >>> extract_wave_summary("## Wave W1 done\\nok")
        '## Wave W1 done\\nok'
        >>> extract_wave_summary("")
        ''
    """
    text = (result_text or "").strip()
    if not text:
        return ""
    m = re.search(r"(?ms)^## .+?(?=^## |\Z)", text)
    if m:
        block = m.group(0).strip()
        return block[:limit] if len(block) > limit else block
    return text[:limit]


def enrich_brief_with_graph_pack(
    brief: dict[str, object],
    *,
    wave_targets: list[str],
    graph_store: GraphStore | str,
    at_sha: str,
    grep_brief: bool = False,
    run_dir: Path | None = None,
    open_findings: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Attach a graph-packed subgraph to *brief*, or restore grep-brief directives."""
    directives = _brief_str_list(brief, "agent_directives")
    if grep_brief:
        brief["grep_brief"] = True
        if directives:
            brief["agent_directives"] = [
                GREP_EXPLORATION_DIRECTIVE if d == GRAPH_PACKED_DIRECTIVE else d for d in directives
            ]
        return brief

    from tripll.serve.brief_packer import pack_brief

    wave_id = str(brief.get("wave_id") or "")
    packed = pack_brief(
        wave={"id": wave_id, "targets": wave_targets},
        graph_store=graph_store,
        at_sha=at_sha,
        open_findings=open_findings,
        run_dir=run_dir,
    )
    brief["graph_pack"] = packed
    brief["grep_brief"] = False
    return brief


def _brief_str_list(brief: dict[str, object], key: str) -> list[str]:
    """Return *key* from *brief* as a list of strings (empty when missing or wrong type)."""
    raw = brief.get(key)
    if isinstance(raw, list):
        return [str(x) for x in raw]
    return []


def render_json_brief(
    node: WaveNode,
    *,
    run_id: str,
    branch: str,
    worktree_path: str,
    plan_worktree_path: str = "",
    prerequisite_waves: list[str] | None = None,
    bullets_in_scope: int = 0,
    locked_decisions: list[str] | None = None,
    manual_smoke_deferred: list[str] | None = None,
    model: str | None = None,
    orchestrator: OrchestratorConfig | None = None,
    role_dispatch: bool | None = None,
    handoff_in: dict[str, object] | None = None,
    outcome_contract: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build the JSON dispatch-brief dict for *node* (design-note §2 schema).

    Args:
        node (WaveNode): The wave to dispatch.
        run_id (str): Run identifier.
        branch (str): Branch the worktree is on.
        worktree_path (str): Worktree checkout path.
        plan_worktree_path (str): Absolute path to the staged plan in the worktree.
        prerequisite_waves (list[str] | None): node_ids that must be done first.
        bullets_in_scope (int): Bullet count for the wave.
        locked_decisions (list[str] | None): Applicable locked-decision ids.
        manual_smoke_deferred (list[str] | None): Deferred manual smoke items.
        model (str | None): Per-wave model override from the execution graph.
        orchestrator (OrchestratorConfig | None): Orchestrator-mode config for directives/agents.
        role_dispatch (bool | None): Resolved toggle from engine; ``None`` implies
            orchestrator mode when ``orchestrator.enabled``.
        handoff_in (dict[str, object] | None): Prior-wave 10-field handoff block.
        outcome_contract (dict[str, object] | None): ``[waves.outcome]`` contract.

    Returns:
        dict[str, object]: The dispatch brief.

    Examples:
        >>> from tripll.graph import WaveNode
        >>> node = WaveNode("l:W1", "l", "plan.md", "W1", "lane", owned_paths=["src/x/"])
        >>> brief = render_json_brief(
        ...     node, run_id="r1", branch="b", worktree_path="/wt",
        ... )
        >>> brief["wave_id"], brief["node_id"]
        ('W1', 'l:W1')
    """
    wave_model = model or node.model
    if orchestrator and orchestrator.enabled and orchestrator.model_policy in ("inherit", "auto"):
        wave_model = None
    commit_subject = ""
    if orchestrator and orchestrator.enabled:
        commit_subject = orchestrator.commit_subjects.get(node.wave_id, "")
    directives = (
        orchestrator_directives(orchestrator, node.wave_id, commit_subject=commit_subject)
        if orchestrator and orchestrator.enabled
        else list(AGENT_DIRECTIVES)
    )
    brief: dict[str, object] = {
        "$schema": "https://tripll/schemas/dispatch-brief.v1.json",
        "brief_version": BRIEF_VERSION,
        "run_id": run_id,
        "node_id": node.node_id,
        "plan_file": node.plan_file,
        "wave_id": node.wave_id,
        "branch": branch,
        "worktree_path": worktree_path,
        "plan_worktree_path": plan_worktree_path or node.plan_file,
        "prerequisite_waves": prerequisite_waves or node.depends_on,
        "bullets_in_scope": bullets_in_scope,
        "specs_with_10x_row": "none",
        "locked_decisions": locked_decisions or [],
        "owned_paths": node.owned_paths,
        "forbidden_paths": node.forbidden_paths,
        "workspace_scope": compute_workspace_scope(node.owned_paths),
        "verify_targets": node.verify_targets,
        "docs_menu_sync_targets": node.docs_menu_sync,
        "manual_smoke_deferred": manual_smoke_deferred or [],
        "wall_clock_limit_s": node.wall_clock_limit_s,
        "retry_policy": {"max_attempts": 5, "on_5th_failure": "escalate"},
        "agent_directives": directives,
        "model": wave_model,
        "handoff_governing_rule": HANDOFF_GOVERNING_RULE,
    }
    if handoff_in:
        brief["handoff_in"] = handoff_in
    if outcome_contract:
        brief["outcome_contract"] = outcome_contract
    if role_dispatch is None:
        inject_agent = bool(orchestrator and orchestrator.enabled)
    else:
        inject_agent = role_dispatch
    if inject_agent:
        agent_test = orchestrator.agent_test if orchestrator else "test-creator"
        agent_wave = orchestrator.agent_wave if orchestrator else "wave-runner"
        brief["agent"] = agent_test if node.role == "test-author" else agent_wave
    if orchestrator and orchestrator.enabled:
        brief["orchestrator_context"] = {
            "feature_branch": orchestrator.feature_branch,
            "ci_base": orchestrator.ci_base,
            "verify_target": orchestrator.verify_target,
        }
    return brief


def render_human_brief(
    node: WaveNode,
    *,
    branch: str,
    worktree_path: str,
    prerequisite_waves: list[str] | None = None,
    bullets_in_scope: int = 0,
    locked_decisions: list[str] | None = None,
    manual_smoke_deferred: list[str] | None = None,
) -> str:
    """Build the wave-runner "Quick start template" text for *node*.

    Args:
        node (WaveNode): The wave to dispatch.
        branch (str): Branch the worktree is on.
        worktree_path (str): Worktree checkout path.
        prerequisite_waves (list[str] | None): node_ids that must be done first.
        bullets_in_scope (int): Bullet count for the wave.
        locked_decisions (list[str] | None): Applicable locked-decision ids.
        manual_smoke_deferred (list[str] | None): Deferred manual smoke items.

    Returns:
        str: The human-readable dispatch brief.

    Examples:
        >>> from tripll.graph import WaveNode
        >>> node = WaveNode("l:W1", "l", "plan.md", "W1", "lane", owned_paths=["src/x/"])
        >>> text = render_human_brief(node, branch="b", worktree_path="/wt")
        >>> "Wave: W1" in text and "Branch / worktree: b" in text
        True
    """
    prereqs = ", ".join(prerequisite_waves or node.depends_on) or "none"
    locked = ", ".join(locked_decisions or []) or "none"
    manual = ", ".join(manual_smoke_deferred or []) or "none"
    owned = ", ".join(node.owned_paths) or "none"
    forbidden = ", ".join(node.forbidden_paths) or "none"
    verify = " ".join(node.verify_targets) or "make ci-affected"
    scope = ", ".join(compute_workspace_scope(node.owned_paths))
    return (
        f"Wave: {node.wave_id}\n"
        f"Plan: {node.plan_file}\n"
        f"Branch / worktree: {branch} ({worktree_path})\n"
        f"Prerequisite waves: {prereqs}\n"
        f"Bullets in scope: {bullets_in_scope}\n"
        f"Specs with matching ### 10.X row: none (package-only plan)\n"
        f"Locked decisions that apply: {locked}\n"
        f"Lane owned paths: {owned}\n"
        f"Workspace scope: {scope}\n"
        f"Verification targets: {verify}\n"
        f"Manual smoke (deferred to user): {manual}\n"
        f"Parallel lane file boundary: edit only owned paths; FORBID {forbidden}\n"
        f"Leave changes staged; do not commit; do not run full make ci."
    )


def render_dispatch_prompt(brief: dict[str, object]) -> str:
    """Build the human-readable agent prompt from a dispatch *brief* dict.

    Args:
        brief (dict[str, object]): A brief from :func:`render_json_brief`.

    Returns:
        str: Prompt text for ``claude -p`` / similar backends.

    Examples:
        >>> prompt = render_dispatch_prompt({
        ...     "wave_id": "W1", "plan_worktree_path": "/wt/plan/tripll/x-wave-plan.md",
        ...     "branch": "wave/r/l-w1", "worktree_path": "/wt",
        ...     "owned_paths": ["src/a.py"], "forbidden_paths": ["src/b.py"],
        ...     "verify_targets": ["make ci-changed"], "node_id": "l:W1",
        ...     "plan_file": "x-wave-plan.md", "prerequisite_waves": [],
        ...     "workspace_scope": ["src/a.py", "plan/tripll"],
        ...     "agent_directives": ["Do not commit."],
        ... })
        >>> "Execute wave W1" in prompt
        True
    """
    wave_id = str(brief.get("wave_id", ""))
    plan_path = str(brief.get("plan_worktree_path") or brief.get("plan_file", ""))
    branch = str(brief.get("branch", ""))
    worktree_path = str(brief.get("worktree_path", ""))
    owned = ", ".join(_brief_str_list(brief, "owned_paths")) or "none"
    forbidden = ", ".join(_brief_str_list(brief, "forbidden_paths")) or "none"
    scope = ", ".join(_brief_str_list(brief, "workspace_scope")) or owned
    verify = " ".join(_brief_str_list(brief, "verify_targets")) or "make ci-affected"
    prereqs = ", ".join(_brief_str_list(brief, "prerequisite_waves")) or "none"
    model = str(brief.get("model") or "").strip()
    orch_ctx = brief.get("orchestrator_context")
    prior_commits = brief.get("prior_wave_commits")
    prefix: list[str] = []
    if isinstance(orch_ctx, dict):
        fb = str(orch_ctx.get("feature_branch") or "").strip()
        if fb:
            prefix.append(f"Orchestrator mode — integration branch: `{fb}`")
        if isinstance(prior_commits, dict) and prior_commits:
            shas = ", ".join(f"{w}={c[:12]}" for w, c in prior_commits.items())
            prefix.append(f"Prior wave commits: {shas}")
    lines = [
        *prefix,
        f"Execute wave {wave_id} from the staged plan slice at {plan_path}.",
        "Read only that wave slice and any files under plan/tripll/ for this wave.",
        "",
        f"Branch: {branch}",
        f"Worktree: {worktree_path}",
        f"Prerequisite waves: {prereqs}",
        f"Owned paths: {owned}",
        f"Workspace scope (read/edit only these + toolchain): {scope}",
        f"Forbidden paths: {forbidden}",
        f"Verification targets: {verify}",
    ]
    if model:
        lines.append(f"Model tier (plan): {model}")
    directives = _brief_str_list(brief, "agent_directives")
    if directives:
        lines += ["", "Agent directives:"]
        lines += [f"- {d}" for d in directives]
    graph_pack = brief.get("graph_pack")
    if isinstance(graph_pack, dict) and graph_pack and not brief.get("grep_brief"):
        lines += ["", "## Packed subgraph"]
        seeds = graph_pack.get("seeds") or []
        if seeds:
            lines.append("Seeds: " + ", ".join(str(s) for s in seeds))
        finding_paths = graph_pack.get("finding_paths") or []
        if finding_paths:
            lines.append("")
            lines.append("Finding paths:")
            for item in finding_paths:
                if isinstance(item, dict):
                    lines.append(f"- {item.get('finding_id')}: {item.get('path')}")
        triple_table = str(graph_pack.get("triple_table") or "").strip()
        if triple_table:
            lines += ["", triple_table]
    handoff = brief.get("handoff_in")
    if isinstance(handoff, dict) and handoff:
        lines += ["", format_handoff_block(handoff)]
    else:
        lines += ["", f"> {HANDOFF_GOVERNING_RULE}"]
    outcome = brief.get("outcome_contract")
    if isinstance(outcome, dict) and outcome:
        req_items = outcome.get("required") or []
        forbid_items = outcome.get("forbidden") or []
        lines += ["", "## Outcome contract"]
        if req_items:
            lines.append("Required: " + "; ".join(str(x) for x in req_items))
        if forbid_items:
            lines.append("Forbidden: " + "; ".join(str(x) for x in forbid_items))
    if isinstance(orch_ctx, dict):
        lines += [
            "",
            "Orchestrator verify (repo root): "
            f"SEVN_CI_BASE={orch_ctx.get('ci_base', 'origin/test-pre')} "
            f"make {orch_ctx.get('verify_target', 'partial-ci')}",
        ]
    else:
        lines += [
            "",
            "Leave changes staged; do not commit; do not run full make ci; "
            "do not edit forbidden_paths or paths outside owned_paths.",
        ]
    return "\n".join(lines)


def write_brief(brief: dict[str, object], briefs_dir: Path) -> Path:
    """Write a JSON *brief* to ``<briefs_dir>/<node_id>.json`` and return the path.

    Args:
        brief (dict[str, object]): A brief from :func:`render_json_brief`.
        briefs_dir (Path): Destination directory.

    Returns:
        Path: The written brief path.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as d:
        ...     p = write_brief({"node_id": "l:W1", "wave_id": "W1"}, Path(d))
        ...     p.suffix == ".json" and p.exists()
        True
    """
    briefs_dir.mkdir(parents=True, exist_ok=True)
    node_id = str(brief["node_id"]).replace(":", "_").replace("/", "_")
    path = briefs_dir / f"{node_id}.json"
    path.write_text(json.dumps(brief, indent=2))
    return path
