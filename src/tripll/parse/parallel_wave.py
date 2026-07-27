"""tripll.parse.parallel_wave — Mode A parser (parallel-wave.md → RunGraph).

Parses an existing ``parallel-wave.md`` set (plan index, lane table, batch
sequencing, hard dependencies) into a validated :class:`~tripll.graph.RunGraph`.
Ports the W0 spike (``wave-orchestrator/spike/parse_dev_eval.py``) onto the
canonical graph dataclasses and the shared markdown helpers.

Exports:
    BATCH_ORDER — canonical Pre-0 → … → Final batch sequence.
    LANE_BATCH_MAP — lane-name → batch-id mapping for the dev_eval set.
    FINAL_GATE_COMMANDS — make targets run at the Final batch gate.
    build_run_graph — build a RunGraph from raw markdown texts.
    build_run_graph_from_dir — read a Mode A directory and build a RunGraph.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from tripll.graph import (
    CW_HOTSPOTS,
    Batch,
    Lane,
    RunGraph,
    WaveNode,
    batch_cw_seams,
    derive_forbidden_paths,
)
from tripll.parse.markdown import find_table_rows, strip_md
from tripll.parse.orchestrator_prompt import attach_orchestrator_config

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Batch sequencing (from parallel-wave-orchestrator-prompt.md §Batch sequencing)
# ---------------------------------------------------------------------------

BATCH_ORDER: list[tuple[str, str, bool]] = [
    ("Pre-0", "HUMAN GATE — research + operator decisions", True),
    ("A", "Coordination + no-backend-dep starts", False),
    ("B", "Telemetry lane", False),
    ("C", "Self-improve lane", False),
    ("D", "Gateway UX + P1", False),
    ("E", "Independent", False),
    ("F", "Upstream intel", False),
    ("G", "Remote deploy", False),
    ("H", "Hermes messaging", False),
    ("I", "Hermes features", False),
    ("Final", "Whole-tree integration gate", False),
]

LANE_BATCH_MAP: dict[str, str] = {
    "Telemetry": "B",
    "Self-improve": "C",
    "Gateway UX": "D",
    "Evolution": "E",
    "Tunnels / infra": "E",
    "Second brain": "E",
    "Honesty / labels": "E",
    "Honesty": "E",
    "Upstream intel": "F",
    "Deploy": "G",
    "Hermes messaging": "H",
    "Hermes features": "I",
    "Voice (P1)": "D",
    "Coding agents (P1)": "D",
    "Browser nodriver": "E",
    "Printing Press": "E",
    "SkillSpector (P1)": "E",
}

FINAL_GATE_COMMANDS: list[str] = [
    "make ci",
    "make mc-e2e",
    "make spy-hermes-check",
    "make hermes-messaging-parity-check",
    "make hermes-features-parity-check",
    "make skillspector-check",
]


def _lane_id(lane_name: str) -> str:
    """Return the sanitised lane id for a lane display name.

    Args:
        lane_name (str): Display name from the lane table.

    Returns:
        str: Lowercase, slug-safe lane id.

    Examples:
        >>> _lane_id("Tunnels / infra")
        'tunnels-infra'
    """
    slug = lane_name.lower().replace("/", " ").strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug


def _parse_lane_table(text: str) -> dict[str, list[str]]:
    """Return ``{lane_name: [owned_path, ...]}`` from the lane table."""
    lanes: dict[str, list[str]] = {}
    for cells in find_table_rows(text, ["Lane", "Plans", "Owned paths"]):
        if len(cells) < 3:
            continue
        lane_name = strip_md(cells[0])
        paths = [p.strip().strip("`") for p in cells[2].split(",") if p.strip()]
        paths = [p for p in paths if p and not p.startswith("…")]
        if lane_name:
            lanes[lane_name] = paths
    return lanes


def _parse_plan_index(text: str) -> list[dict[str, object]]:
    """Return ``[{num, title, effort, lane}]`` from the plan index table."""
    plans: list[dict[str, object]] = []
    for cells in find_table_rows(text, ["#", "Plan", "Effort"]):
        if len(cells) < 4:
            continue
        try:
            num = int(cells[0].strip())
        except ValueError:
            continue
        link = re.search(r"\[([^\]]+)\]\(([^)]+)\)", cells[1])
        title = link.group(1) if link else cells[1].strip()
        plan_file = link.group(2) if link else ""
        plans.append(
            {
                "num": num,
                "title": title,
                "plan_file": plan_file,
                "effort": cells[2].strip(),
                "lane": strip_md(cells[3]),
            }
        )
    return plans


def _parse_pre0_gates(text: str) -> list[str]:
    """Extract Pre-0 gate items from the orchestrator-prompt table."""
    gates: list[str] = []
    for cells in find_table_rows(text, ["Gate", "Plan", "Decision needed"]):
        if len(cells) < 3:
            continue
        gate = strip_md(cells[0])
        if gate:
            gates.append(f"{gate} ({cells[1].strip()}): {cells[2].strip()}")
    return gates


_PRE0_FALLBACK: list[str] = [
    "Provider attr contract (#1 W0): confirm canonical provider.call attrs",
    "Proposer shape (#2 W0): structured-output vs tool-agent; model slot",
    "Auto-run import (#4 AR-0): webhook-only, created-only, dry-run",
    "Tunnels path (#7): Path A (relabel) or Path B (cloudflared manager)",
    "Second-brain path (#8): W0 relabel only, or W1-3 Witchcraft",
    "RLM relabel (#9): confirm Path A (rename 'RLM Config')",
    "spy_hermes taxonomy (#12 H0): confirm feature taxonomy + sources",
    "Remote deploy inventory (#13 RD0): confirm SSH inventory + staging host",
    "Hermes messaging tiers (#14 M0): parity JSON + Tier 1-3 order (BLOCKING)",
    "Hermes features matrix (#15 F0): gap JSON + dedup vs #2/#3/#6 (BLOCKING)",
    "Voice decisions D1-D10 (#16 W0): inbound-always, session override, Kokoro port",
    "Coding-agents arch (#17 CA0): agent types, binding model, executor list (BLOCKING)",
    "nodriver attach spike (#18 ND0): CDP attach API + AGPL note + action table",
    "Printing Press registry (#19 PP0): registry.json format + starter-pack install",
    "SkillSpector thresholds (#20 SS0): bundled scan + threshold sign-off",
]


FINAL_GATE_COMMANDS_MODE_B: list[str] = ["make ci"]


def build_run_graph(
    parallel_wave_text: str,
    review_text: str | None,
    orchestrator_text: str | None,
    *,
    run_id: str,
    batch_assignments: list[tuple[str, list[str]]] | None = None,
    pre0_gates_override: list[str] | None = None,
) -> RunGraph:
    """Build a :class:`RunGraph` from Mode A markdown texts.

    Args:
        parallel_wave_text (str): Contents of ``parallel-wave.md``.
        review_text (str | None): Contents of ``parallel-wave-review.md``.
        orchestrator_text (str | None): Contents of the orchestrator-prompt.
        run_id (str): Run identifier.
        batch_assignments (list[tuple[str, list[str]]] | None): Mode B batch
            order as ``(batch_id, [lane_display_name, ...])``; when set, the
            dev_eval ``BATCH_ORDER`` template is not used.
        pre0_gates_override (list[str] | None): Explicit Pre-0 gates (Mode B);
            when set (including ``[]``), dev_eval fallback gates are skipped.

    Returns:
        RunGraph: One lane-level wave node per lane, batches Pre-0 → Final.

    Examples:
        >>> md = (
        ...     "| # | Plan | Effort | Lane |\\n|---|--|--|--|\\n"
        ...     "| 1 | [a](a.md) | M | Telemetry |\\n\\n"
        ...     "| Lane | Plans | Owned paths |\\n|--|--|--|\\n"
        ...     "| Telemetry | #1 | `src/sevn/agent/` |\\n"
        ... )
        >>> g = build_run_graph(md, None, None, run_id="r")
        >>> g.batch_order()[0], g.batch_order()[-1]
        ('Pre-0', 'Final')
    """
    graph = RunGraph(run_id=run_id, source_mode="A" if batch_assignments is None else "B")

    lane_table = _parse_lane_table(parallel_wave_text)
    plan_index = _parse_plan_index(parallel_wave_text)
    lane_name_by_id = {_lane_id(name): name for name in lane_table}

    # Build lanes + assign plans.
    for lane_name, owned in lane_table.items():
        lid = _lane_id(lane_name)
        lane = Lane(lane_id=lid, owned_paths=owned)
        for plan in plan_index:
            if strip_md(str(plan["lane"])) == lane_name:
                lane.plans.append(f"plan-{plan['num']}")
        graph.lanes[lid] = lane

    # One lane-level wave node per lane (full per-wave nodes in later waves).
    for lid, lane in graph.lanes.items():
        lane_name = lane_name_by_id.get(lid, lid)
        effort = "M"
        plan_file = f"<{lid}-plan>"
        for plan in plan_index:
            if strip_md(str(plan["lane"])) == lane_name:
                effort = str(plan["effort"]).split("\u2013")[0].split("/")[0].strip() or "M"
                plan_file = str(plan["plan_file"]) or plan_file
                break
        wall_clock = 5400 if "XL" in effort else 2700
        node_id = f"{lid}:all-waves"
        node = WaveNode(
            node_id=node_id,
            plan_id=lid,
            plan_file=plan_file,
            wave_id="W0->Final",
            lane=lane_name,
            owned_paths=lane.owned_paths,
            forbidden_paths=derive_forbidden_paths(lid, graph.lanes),
            effort=effort,
            wall_clock_limit_s=wall_clock,
        )
        graph.nodes[node_id] = node
        lane.waves.append(node)

    # Build batches — Mode B uses derived assignments; Mode A uses dev_eval template.
    if batch_assignments is not None:
        for batch_id, lane_names in batch_assignments:
            lane_ids = [_lane_id(n) for n in lane_names]
            is_gate = batch_id == "Pre-0"
            if batch_id == "Pre-0":
                label = "HUMAN GATE — operator decisions"
            elif batch_id == "Final":
                label = "Integration gate"
            else:
                label = ", ".join(lane_names) if lane_names else f"Batch {batch_id}"
            cw = batch_cw_seams(batch_id)
            graph.batches.append(
                Batch(
                    batch_id=batch_id,
                    label=label,
                    lanes=lane_ids,
                    is_human_gate=is_gate,
                    gate_commands=(FINAL_GATE_COMMANDS_MODE_B if batch_id == "Final" else []),
                    cw_seams=cw,
                    merge_order=lane_ids,
                )
            )
    else:
        batch_lane_map: dict[str, list[str]] = {bid: [] for bid, _, _ in BATCH_ORDER}
        for lid in graph.lanes:
            lane_name = lane_name_by_id.get(lid, lid)
            batch_id = LANE_BATCH_MAP.get(lane_name, "E")
            batch_lane_map.setdefault(batch_id, []).append(lid)

        for batch_id, label, is_gate in BATCH_ORDER:
            cw = batch_cw_seams(batch_id)
            graph.batches.append(
                Batch(
                    batch_id=batch_id,
                    label=label,
                    lanes=batch_lane_map.get(batch_id, []),
                    is_human_gate=is_gate,
                    gate_commands=FINAL_GATE_COMMANDS if batch_id == "Final" else [],
                    cw_seams=cw,
                    merge_order=batch_lane_map.get(batch_id, []),
                )
            )

    graph.cw_seams = {cw: [] for cw in CW_HOTSPOTS}

    if pre0_gates_override is not None:
        graph.pre0_gates = list(pre0_gates_override)
    elif orchestrator_text:
        graph.pre0_gates = _parse_pre0_gates(orchestrator_text)
    elif batch_assignments is None and not graph.pre0_gates:
        graph.pre0_gates = list(_PRE0_FALLBACK)

    return graph


def _attach_orchestrator_from_dir(graph: RunGraph, input_dir: Path) -> RunGraph:
    """Attach orchestrator config when a prompt file exists in *input_dir*."""
    wave_plans = sorted(input_dir.glob("*-wave-plan.md"))
    wave_text = wave_plans[0].read_text() if wave_plans else None
    slug = wave_plans[0].stem.replace("-wave-plan", "") if wave_plans else None
    return attach_orchestrator_config(
        graph,
        input_dir,
        slug=slug,
        wave_plan_text=wave_text,
    )


def build_run_graph_from_dir(input_dir: Path, *, run_id: str) -> RunGraph:
    """Read a Mode A directory and build a :class:`RunGraph`.

    Args:
        input_dir (Path): Directory containing ``parallel-wave.md`` (required)
            and optionally ``parallel-wave-review.md`` and the orchestrator
            prompt.
        run_id (str): Run identifier.

    Returns:
        RunGraph: The derived run graph.

    Raises:
        FileNotFoundError: If ``parallel-wave.md`` is absent.

    Examples:
        >>> callable(build_run_graph_from_dir)
        True
    """
    pw = input_dir / "parallel-wave.md"
    if not pw.exists():
        raise FileNotFoundError(f"parallel-wave.md not found in {input_dir}")
    review = input_dir / "parallel-wave-review.md"
    orch = input_dir / "parallel-wave-orchestrator-prompt.md"
    return _attach_orchestrator_from_dir(
        build_run_graph(
            pw.read_text(),
            review.read_text() if review.exists() else None,
            orch.read_text() if orch.exists() else None,
            run_id=run_id,
        ),
        input_dir,
    )
