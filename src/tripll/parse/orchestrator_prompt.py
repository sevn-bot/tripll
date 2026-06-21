"""tripll.parse.orchestrator_prompt — parse ``*-orchestrator-prompt.md`` files.

Discovers orchestrator prompt files in an input directory (Mode A + B), extracts
wave order, feature branch, verify/commit policy, MODEL POLICY, and REPORTING
FORMAT columns. Builds :class:`~tripll.graph.OrchestratorConfig` when
orchestrator mode is active (D1).

Exports:
    ParsedOrchestratorPrompt — raw parse result from one prompt file.
    discover_orchestrator_prompt — locate the prompt file in an input dir.
    parse_orchestrator_prompt — parse prompt markdown text.
    parse_orchestrator_mode — read ``orchestrator_mode`` from a wave plan.
    build_orchestrator_config — attach config when mode is enabled.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from tripll.graph import OrchestratorConfig, RunGraph
from tripll.parse.markdown import find_table_rows, slice_section, strip_md

if TYPE_CHECKING:
    from pathlib import Path

_ORCHESTRATOR_GLOB = "*orchestrator-prompt.md"
_WAVE_ID_RE = re.compile(r"\b(W\d+|Final|Pre-0)\b", re.IGNORECASE)
_GATE_IN_BRACKETS = re.compile(r"\[([^\]]+)\]")


@dataclass
class WaveVerifyCommit:
    """Per-wave verify target and commit subject from the orchestrator prompt."""

    wave_id: str
    verify: str = "partial-ci"
    fallback_verify: str = ""
    commit_subject: str = ""


@dataclass
class ParsedOrchestratorPrompt:
    """Structured parse result for one orchestrator prompt file."""

    prompt_path: str
    feature_branch: str | None = None
    ci_base: str = "origin/test-pre"
    verify_target: str = "partial-ci"
    single_branch: bool = True
    commit_per_wave: bool = True
    serial_waves: list[str] = field(default_factory=list)
    review_gates: dict[str, str] = field(default_factory=dict)
    wave_verify_commits: list[WaveVerifyCommit] = field(default_factory=list)
    model_policy: str = "inherit"
    agent_wave: str = "wave-runner"
    agent_orchestrator: str = "wave-orchestrator"
    agent_test: str = "test-creator"
    role_dispatch: bool = False
    reporting_columns: list[str] = field(
        default_factory=lambda: [
            "Wave",
            "Status",
            "Branch",
            "Commit",
            "Evidence / blockers",
        ]
    )


def discover_orchestrator_prompt(input_dir: Path, *, slug: str | None = None) -> Path | None:
    """Locate ``*-orchestrator-prompt.md`` in *input_dir* (D1).

    Prefers ``{slug}-orchestrator-prompt.md`` when *slug* is set; otherwise the
    first ``*orchestrator-prompt.md`` match (sorted).

    Args:
        input_dir (Path): Tripll input set directory.
        slug (str | None): Plan slug for preferred filename.

    Returns:
        Path | None: Resolved prompt path, or ``None`` when absent.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as d:
        ...     root = Path(d)
        ...     p = root / "demo-orchestrator-prompt.md"
        ...     _ = p.write_text("# demo")
        ...     discover_orchestrator_prompt(root, slug="demo") == p
        True
    """
    if slug:
        preferred = input_dir / f"{slug}-orchestrator-prompt.md"
        if preferred.is_file():
            return preferred
    matches = sorted(input_dir.glob(_ORCHESTRATOR_GLOB))
    return matches[0] if matches else None


def parse_orchestrator_mode(wave_plan_text: str) -> str | None:
    """Return ``serial`` | ``off`` from wave-plan frontmatter or section.

    Args:
        wave_plan_text (str): Full wave-plan markdown body.

    Returns:
        str | None: Mode value when declared; ``None`` when absent.

    Examples:
        >>> parse_orchestrator_mode("---\\norchestrator_mode: serial\\n---\\n# X")
        'serial'
    """
    fm = re.match(r"^---\s*\n(.*?)\n---", wave_plan_text, re.DOTALL)
    if fm:
        for line in fm.group(1).splitlines():
            m = re.match(r"orchestrator_mode:\s*(\S+)", line.strip(), re.I)
            if m:
                return m.group(1).lower()
    section = slice_section(wave_plan_text, "orchestrator mode")
    for line in section.splitlines():
        m = re.match(r"orchestrator_mode:\s*(\S+)", line.strip(), re.I)
        if m:
            return m.group(1).lower()
    return None


def parse_role_dispatch(wave_plan_text: str) -> bool:
    """Return ``role_dispatch`` from wave-plan frontmatter or body (design-note §10.4).

    Args:
        wave_plan_text (str): Full wave-plan markdown body.

    Returns:
        bool: ``True`` when the plan declares role dispatch on.

    Examples:
        >>> parse_role_dispatch("---\\nrole_dispatch: true\\n---\\n# X")
        True
        >>> parse_role_dispatch("# X\\nrole_dispatch: 1")
        True
        >>> parse_role_dispatch("# X")
        False
    """
    fm = re.match(r"^---\s*\n(.*?)\n---", wave_plan_text, re.DOTALL)
    if fm:
        for line in fm.group(1).splitlines():
            m = re.match(r"role_dispatch:\s*(\S+)", line.strip(), re.I)
            if m:
                return m.group(1).lower() in ("1", "true", "yes", "on")
    for line in wave_plan_text.splitlines():
        m = re.match(r"role_dispatch:\s*(\S+)", line.strip(), re.I)
        if m:
            return m.group(1).lower() in ("1", "true", "yes", "on")
    return False


def _parse_feature_branch(text: str) -> str | None:
    for pattern in (
        r"Feature branch:\s*\*\*`([^`]+)`\*\*",
        r"Feature branch:\s*`([^`]+)`",
        r"Single integration branch:\*\*\s*`([^`]+)`",
        r"Single branch:\s*`([^`]+)`",
        r"branch:\s*`([^`]+)`",
    ):
        m = re.search(pattern, text, re.I)
        if m:
            return m.group(1).strip()
    return None


def _parse_ci_base(text: str) -> str:
    m = re.search(r"SEVN_CI_BASE\s*=\s*(\S+)", text)
    if not m:
        return "origin/test-pre"
    return m.group(1).strip().strip("`")


def _parse_serial_waves_from_codeblock(text: str) -> list[str]:
    section = slice_section(text, "Wave execution order")
    if not section:
        section = text
    for block in re.finditer(r"```(?:text)?\s*\n(.*?)```", section, re.DOTALL):
        body = block.group(1)
        if "→" in body or "->" in body:
            waves: list[str] = []
            for token in re.split(r"\s*(?:→|->)\s*", body.strip()):
                token = token.strip()
                if not token:
                    continue
                gate_m = _GATE_IN_BRACKETS.search(token)
                if gate_m:
                    continue
                wid = _WAVE_ID_RE.search(token)
                if wid:
                    label = wid.group(1)
                    if label.lower() == "final":
                        label = "Final"
                    if label not in waves:
                        waves.append(label)
            if waves:
                return waves
    return []


def _parse_serial_waves_from_table(text: str) -> list[str]:
    waves: list[str] = []
    for cells in find_table_rows(text, ["Order", "Wave"]):
        if len(cells) < 2:
            continue
        wave_cell = strip_md(cells[1])
        wid = _WAVE_ID_RE.search(wave_cell)
        if not wid:
            continue
        label = wid.group(1)
        if label.lower() == "final":
            label = "Final"
        if label not in waves:
            waves.append(label)
    if waves:
        return waves
    for cells in find_table_rows(text, ["Wave", "Depends"]):
        if len(cells) < 1:
            continue
        wave_cell = strip_md(cells[0])
        wid = _WAVE_ID_RE.search(wave_cell)
        if not wid:
            continue
        label = wid.group(1)
        if label.lower() == "final":
            label = "Final"
        if label not in waves:
            waves.append(label)
    return waves


def _parse_review_gates(text: str) -> dict[str, str]:
    gates: dict[str, str] = {}
    for cells in find_table_rows(text, ["Order", "Wave"]):
        if len(cells) < 5:
            continue
        wave_cell = strip_md(cells[1])
        gate_cell = strip_md(cells[4]) if len(cells) > 4 else ""
        wid = _WAVE_ID_RE.search(wave_cell)
        if not wid:
            continue
        wave_id = wid.group(1)
        if wave_id.lower() == "final":
            wave_id = "Final"
        gate_m = re.search(r"(W\d+\.\d+)", gate_cell, re.I)
        if gate_m:
            gates[wave_id] = gate_m.group(1).upper().replace("W", "W", 1)
        elif "review" in gate_cell.lower() and "yes" in gate_cell.lower():
            gate_m2 = re.search(r"(W\d+\.\d+)", gate_cell, re.I)
            if gate_m2:
                gates[wave_id] = gate_m2.group(1)
    for cells in find_table_rows(text, ["Wave", "Gate"]):
        if len(cells) < 2:
            continue
        wave_cell = strip_md(cells[0])
        gate_cell = strip_md(cells[1])
        wid = _WAVE_ID_RE.search(wave_cell)
        gate_m = re.search(r"(W\d+\.\d+)", gate_cell, re.I)
        if wid and gate_m:
            wave_id = wid.group(1)
            if wave_id.lower() != "final":
                gates[wave_id] = gate_m.group(1)
    for block in re.finditer(r"\[(W\d+\.\d+)\s+REVIEW GATE\]", text, re.I):
        gate_label = block.group(1)
        wave_m = re.match(r"(W\d+)", gate_label, re.I)
        if wave_m:
            gates[wave_m.group(1)] = gate_label
    return gates


def _parse_wave_verify_commits(text: str) -> list[WaveVerifyCommit]:
    section = slice_section(text, "Per-wave verification")
    if not section:
        section = slice_section(text, "Per-wave commit")
    if not section:
        section = text
    rows: list[WaveVerifyCommit] = []
    for cells in find_table_rows(section, ["Wave", "Verify"]):
        if len(cells) < 2:
            continue
        wave_cell = strip_md(cells[0])
        wid = _WAVE_ID_RE.search(wave_cell)
        if not wid:
            continue
        wave_id = wid.group(1)
        if wave_id.lower() == "final":
            wave_id = "Final"
        verify = strip_md(cells[1]) if len(cells) > 1 else "partial-ci"
        fallback = strip_md(cells[2]) if len(cells) > 2 else ""
        commit = strip_md(cells[3]) if len(cells) > 3 else ""
        rows.append(
            WaveVerifyCommit(
                wave_id=wave_id,
                verify=verify,
                fallback_verify=fallback,
                commit_subject=commit,
            )
        )
    for cells in find_table_rows(section, ["Wave", "Suggested commit"]):
        if len(cells) < 2:
            continue
        wave_cell = strip_md(cells[0])
        wid = _WAVE_ID_RE.search(wave_cell)
        if not wid:
            continue
        wave_id = wid.group(1)
        if wave_id.lower() == "final":
            wave_id = "Final"
        commit = strip_md(cells[1])
        existing = next((r for r in rows if r.wave_id == wave_id), None)
        if existing:
            if commit and not existing.commit_subject:
                existing.commit_subject = commit
        else:
            rows.append(WaveVerifyCommit(wave_id=wave_id, commit_subject=commit))
    return rows


def _parse_agent_test(text: str) -> str:
    """Return the ``agent_test`` agent name from prompt text (default ``test-creator``).

    Mirrors the ``agent_wave`` / ``agent_orchestrator`` keys: the tests-first model
    dispatches the ``test-author`` wave to this agent (design-note §9.3).

    Args:
        text (str): Orchestrator prompt markdown body.

    Returns:
        str: Parsed agent name, or ``test-creator`` when the key is absent.

    Examples:
        >>> _parse_agent_test("agent_test: my-tester")
        'my-tester'
        >>> _parse_agent_test("no key here")
        'test-creator'
    """
    m = re.search(r"agent_test:\s*([A-Za-z0-9._-]+)", text, re.I)
    return m.group(1).strip() if m else "test-creator"


def _parse_role_dispatch(text: str) -> bool:
    """Return ``role_dispatch`` from orchestrator prompt text (default off)."""
    m = re.search(r"role_dispatch:\s*(\S+)", text, re.I)
    return m.group(1).lower() in ("1", "true", "yes", "on") if m else False


def _parse_model_policy(text: str) -> str:
    section = slice_section(text, "MODEL POLICY")
    blob = section or text
    if re.search(r"Do NOT pass\s+`model`", blob, re.I):
        return "inherit"
    if re.search(r"\bauto\b", blob, re.I):
        return "auto"
    return "inherit"


def _parse_reporting_columns(text: str) -> list[str]:
    section = slice_section(text, "REPORTING FORMAT")
    if not section:
        return [
            "Wave",
            "Status",
            "Branch",
            "Commit",
            "Evidence / blockers",
        ]
    for cells in find_table_rows(section, ["Wave", "Status"]):
        if len(cells) >= 5:
            return [strip_md(c) for c in cells[:5]]
    m = re.search(
        r"\|\s*Wave\s*\|\s*Status\s*\|\s*Branch\s*\|\s*Commit\s*\|\s*([^|]+)\s*\|",
        section,
        re.I,
    )
    if m:
        return [
            "Wave",
            "Status",
            "Branch",
            "Commit",
            strip_md(m.group(1)),
        ]
    return [
        "Wave",
        "Status",
        "Branch",
        "Commit",
        "Evidence / blockers",
    ]


def _commit_per_wave(text: str) -> bool:
    return bool(
        re.search(r"Commit\s*\+\s*push every wave", text, re.I)
        or re.search(r"commit and push on green", text, re.I)
        or re.search(r"must\s+commit and push", text, re.I)
    )


def parse_orchestrator_prompt(path: Path) -> ParsedOrchestratorPrompt:
    """Parse one orchestrator prompt markdown file.

    Args:
        path (Path): Path to ``*-orchestrator-prompt.md``.

    Returns:
        ParsedOrchestratorPrompt: Extracted orchestrator metadata.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as d:
        ...     p = Path(d) / "x-orchestrator-prompt.md"
        ...     _ = p.write_text("Feature branch: `feature/foo`\\n")
        ...     parse_orchestrator_prompt(p).feature_branch
        'feature/foo'
    """
    text = path.read_text()
    serial = _parse_serial_waves_from_codeblock(text) or _parse_serial_waves_from_table(text)
    wave_rows = _parse_wave_verify_commits(text)
    verify_target = "partial-ci"
    if wave_rows:
        first = wave_rows[0].verify.lower()
        if "partial-ci" in first:
            verify_target = "partial-ci"
        elif "make " in first:
            verify_target = first.replace("make ", "").split()[0]
    return ParsedOrchestratorPrompt(
        prompt_path=str(path),
        feature_branch=_parse_feature_branch(text),
        ci_base=_parse_ci_base(text),
        verify_target=verify_target,
        single_branch=bool(_parse_feature_branch(text)),
        commit_per_wave=_commit_per_wave(text),
        serial_waves=serial,
        review_gates=_parse_review_gates(text),
        wave_verify_commits=wave_rows,
        model_policy=_parse_model_policy(text),
        agent_test=_parse_agent_test(text),
        role_dispatch=_parse_role_dispatch(text),
        reporting_columns=_parse_reporting_columns(text),
    )


def build_orchestrator_config(
    input_dir: Path,
    *,
    slug: str | None = None,
    wave_plan_text: str | None = None,
) -> OrchestratorConfig | None:
    """Build :class:`OrchestratorConfig` when orchestrator mode is active (D1).

    Args:
        input_dir (Path): Input set directory.
        slug (str | None): Plan slug for preferred prompt filename.
        wave_plan_text (str | None): Primary wave-plan text for mode override.

    Returns:
        OrchestratorConfig | None: Config when enabled; ``None`` when off/absent.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as d:
        ...     root = Path(d)
        ...     _ = (root / "x-orchestrator-prompt.md").write_text(
        ...         "Feature branch: `f`\\n```text\\nW0 → W1\\n```\\n")
        ...     cfg = build_orchestrator_config(root)
        ...     cfg is not None and cfg.enabled
        True
    """
    prompt_path = discover_orchestrator_prompt(input_dir, slug=slug)
    if prompt_path is None:
        return None
    mode: str | None = None
    if wave_plan_text:
        mode = parse_orchestrator_mode(wave_plan_text)
    if mode == "off":
        return None
    parsed = parse_orchestrator_prompt(prompt_path)
    commit_subjects = {
        row.wave_id: row.commit_subject for row in parsed.wave_verify_commits if row.commit_subject
    }
    return OrchestratorConfig(
        enabled=True,
        prompt_path=str(prompt_path),
        feature_branch=parsed.feature_branch,
        single_branch=parsed.single_branch,
        commit_per_wave=parsed.commit_per_wave,
        verify_target=parsed.verify_target,
        ci_base=parsed.ci_base,
        serial_waves=list(parsed.serial_waves),
        review_gates=dict(parsed.review_gates),
        commit_subjects=commit_subjects,
        model_policy=parsed.model_policy,
        agent_wave=parsed.agent_wave,
        agent_orchestrator=parsed.agent_orchestrator,
        agent_test=parsed.agent_test,
        role_dispatch=parsed.role_dispatch,
    )


def attach_orchestrator_config(
    graph: RunGraph,
    input_dir: Path,
    *,
    slug: str | None = None,
    wave_plan_text: str | None = None,
) -> RunGraph:
    """Attach ``graph.orchestrator`` when a prompt file is present.

    Args:
        graph (RunGraph): Graph to mutate.
        input_dir (Path): Input set directory.
        slug (str | None): Plan slug for prompt discovery.
        wave_plan_text (str | None): Wave-plan body for mode parsing.

    Returns:
        RunGraph: Same graph with optional ``orchestrator`` set.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from tripll.graph import RunGraph
        >>> with tempfile.TemporaryDirectory() as d:
        ...     root = Path(d)
        ...     _ = (root / "p-orchestrator-prompt.md").write_text("# p")
        ...     g = attach_orchestrator_config(RunGraph(run_id="r"), root)
        ...     g.orchestrator is not None
        True
    """
    graph.orchestrator = build_orchestrator_config(
        input_dir,
        slug=slug,
        wave_plan_text=wave_plan_text,
    )
    if wave_plan_text:
        graph.role_dispatch = parse_role_dispatch(wave_plan_text)
    return graph
