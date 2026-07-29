"""tripll.parse.wave_plan_v1 — machine-readable execution graph in wave-plan files.

Wave plans with a ``## tripll execution graph`` section (format v1) get per-wave
nodes and batches derived from ``depends_on`` / optional ``## tripll batches``.

Exports:
    WaveSpec — one row from the execution graph table.
    BatchSpec — explicit batch assignment (optional).
    WavePlanV1 — parsed v1 plan metadata + graph.
    parse_wave_plan_v1 — parse one ``*-wave-plan.md`` file.
    validate_wave_plan_v1 — structural validation errors (empty if ok).
    build_graph_from_v1_dir — build :class:`~tripll.graph.RunGraph` from v1 set.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from tripll.graph import (
    Batch,
    Lane,
    RunGraph,
    WaveNode,
    batch_cw_seams,
    derive_forbidden_paths,
)
from tripll.parse.markdown import find_table_rows, strip_md
from tripll.parse.orchestrator_prompt import attach_orchestrator_config
from tripll.parse.plan_files import (
    _parse_files_in_scope,
    _slice_section,
    _slug,
    collect_pre0_gates_from_plans,
    parse_plan_file,
)

if TYPE_CHECKING:
    from pathlib import Path

TRIPLL_FORMAT_MARKER = "tripll_format:"
EXEC_GRAPH_HEADING = "tripll execution graph"
BATCHES_HEADING = "tripll batches"

#: Valid values for the optional ``role`` column (design-note §9.1). ``test-author``
#: marks the tests-first wave (dispatched to ``test-creator``); all others default
#: to ``impl``.
_VALID_ROLES = frozenset({"impl", "test-author"})


@dataclass
class WaveSpec:
    """One wave row from the execution graph table."""

    wave_id: str
    title: str = ""
    depends_on: list[str] = field(default_factory=list)
    review_gate: bool = False
    effort: str = "M"
    verify_targets: list[str] = field(default_factory=lambda: ["make ci-affected"])
    model: str | None = None
    role: str = "impl"


@dataclass
class BatchSpec:
    """Explicit batch row from the optional batches table."""

    batch_id: str
    wave_ids: list[str] = field(default_factory=list)
    human_gate: bool = False
    parallel: bool = True


@dataclass
class WavePlanV1:
    """Parsed v1 wave-plan file."""

    plan_file: Path
    plan_id: str
    title: str
    owned_paths: list[str]
    waves: list[WaveSpec]
    batches: list[BatchSpec] = field(default_factory=list)
    format_version: int = 1

    @property
    def has_execution_graph(self) -> bool:
        """True when at least one wave row was parsed."""
        return bool(self.waves)


def _split_csv(value: str) -> list[str]:
    return [p.strip() for p in re.split(r"[,;]", value) if p.strip()]


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"yes", "true", "1", "y"}


def _parse_execution_graph_section(text: str) -> tuple[int, list[WaveSpec]]:
    section = _slice_section(text, EXEC_GRAPH_HEADING)
    if not section and EXEC_GRAPH_HEADING not in text:
        return 0, []
    fmt = 1
    for line in section.splitlines()[:5]:
        if TRIPLL_FORMAT_MARKER in line:
            m = re.search(r"tripll_format:\s*(\d+)", line, re.I)
            if m:
                fmt = int(m.group(1))
    waves: list[WaveSpec] = []
    for cells in find_table_rows(
        section or text,
        ["wave_id", "depends_on"],
    ):
        if len(cells) < 1:
            continue
        wave_id = strip_md(cells[0])
        if not wave_id or wave_id.lower() in {"wave_id", "wave"}:
            continue
        title = strip_md(cells[1]) if len(cells) > 1 else wave_id
        deps_raw = cells[2] if len(cells) > 2 else ""
        review = cells[3] if len(cells) > 3 else ""
        effort = cells[4].strip() if len(cells) > 4 else "M"
        verify = cells[5] if len(cells) > 5 else "make ci-affected"
        model_cell = strip_md(cells[6]) if len(cells) > 6 else ""
        role_cell = strip_md(cells[7]).strip() if len(cells) > 7 else ""
        waves.append(
            WaveSpec(
                wave_id=wave_id,
                title=title,
                depends_on=_split_csv(deps_raw),
                review_gate=_parse_bool(review),
                effort=effort.split()[0] if effort else "M",
                verify_targets=_split_csv(verify) or ["make ci-affected"],
                model=model_cell or None,
                role=role_cell or "impl",
            )
        )
    return fmt, waves


def _parse_batches_section(text: str) -> list[BatchSpec]:
    section = _slice_section(text, BATCHES_HEADING)
    if not section:
        return []
    batches: list[BatchSpec] = []
    for cells in find_table_rows(section, ["batch_id", "waves"]):
        if len(cells) < 2:
            continue
        batch_id = strip_md(cells[0])
        if not batch_id or batch_id.lower() == "batch_id":
            continue
        waves = _split_csv(cells[1])
        human = _parse_bool(cells[2]) if len(cells) > 2 else batch_id == "Pre-0"
        parallel = True
        if len(cells) > 3:
            parallel = _parse_bool(cells[3]) if cells[3].strip() else True
        batches.append(
            BatchSpec(
                batch_id=batch_id,
                wave_ids=waves,
                human_gate=human,
                parallel=parallel,
            )
        )
    return batches


def parse_wave_plan_v1(path: Path) -> WavePlanV1:
    """Parse a wave-plan file for v1 execution graph metadata."""
    text = path.read_text()
    title_m = re.search(r"^#\s+(.+)", text, re.MULTILINE)
    fmt, waves = _parse_execution_graph_section(text)
    return WavePlanV1(
        plan_file=path,
        plan_id=_slug(path),
        title=title_m.group(1).strip() if title_m else _slug(path),
        owned_paths=_parse_files_in_scope(text),
        waves=waves,
        batches=_parse_batches_section(text),
        format_version=fmt,
    )


def validate_wave_plan_v1(path: Path) -> list[str]:
    """Return validation errors for a v1 wave-plan (empty list if ok)."""
    errors: list[str] = []
    text = path.read_text()
    if EXEC_GRAPH_HEADING not in text:
        errors.append(f"{path.name}: missing '## {EXEC_GRAPH_HEADING}' section")
        return errors
    plan = parse_wave_plan_v1(path)
    if not plan.waves:
        errors.append(f"{path.name}: execution graph table has no wave rows")
        return errors
    if not plan.owned_paths:
        errors.append(f"{path.name}: missing owned paths in '## Files in scope'")
    wave_ids = {w.wave_id for w in plan.waves}
    for w in plan.waves:
        for dep in w.depends_on:
            if dep not in wave_ids:
                errors.append(f"{path.name}: wave {w.wave_id} depends on unknown '{dep}'")
        if w.role not in _VALID_ROLES:
            errors.append(
                f"{path.name}: wave {w.wave_id} has invalid role '{w.role}' "
                f"(expected one of {sorted(_VALID_ROLES)})"
            )
    # Cycle detection
    visiting: set[str] = set()
    done: set[str] = set()

    def dfs(wid: str) -> bool:
        if wid in done:
            return False
        if wid in visiting:
            return True
        visiting.add(wid)
        spec = next(x for x in plan.waves if x.wave_id == wid)
        if any(dfs(d) for d in spec.depends_on):
            return True
        visiting.remove(wid)
        done.add(wid)
        return False

    for w in plan.waves:
        if dfs(w.wave_id):
            errors.append(f"{path.name}: dependency cycle involving {w.wave_id}")
            break
    if plan.batches:
        for b in plan.batches:
            for wid in b.wave_ids:
                if wid not in wave_ids:
                    errors.append(
                        f"{path.name}: batch {b.batch_id} references unknown wave '{wid}'"
                    )
    return errors


def _effort_seconds(effort: str) -> int:
    return 5400 if "XL" in effort.upper() else 2700


def _infer_batches_from_waves(waves: list[WaveSpec]) -> list[BatchSpec]:
    """Topological layers → one batch per ready layer (deterministic serial default)."""
    wave_map = {w.wave_id: w for w in waves}
    resolved: set[str] = set()
    remaining = {w.wave_id for w in waves}
    batches: list[BatchSpec] = []
    review_waves = [w.wave_id for w in waves if w.review_gate]
    if review_waves:
        batches.append(BatchSpec(batch_id="Pre-0", wave_ids=review_waves, human_gate=True))
        resolved.update(review_waves)
        remaining.difference_update(review_waves)
    letter_ord = ord("A")
    guard = len(waves) + 5
    i = 0
    while remaining and i < guard:
        ready = sorted(
            wid for wid in remaining if all(d in resolved for d in wave_map[wid].depends_on)
        )
        if not ready:
            ready = sorted(remaining)
        batch_id = chr(letter_ord) if letter_ord <= ord("Z") else f"X{letter_ord - ord('Z')}"
        if any(wid.lower() == "final" for wid in ready):
            non_final = [w for w in ready if w.lower() != "final"]
            final = [w for w in ready if w.lower() == "final"]
            if non_final:
                batches.append(BatchSpec(batch_id=batch_id, wave_ids=non_final))
                resolved.update(non_final)
                remaining.difference_update(non_final)
                letter_ord += 1
            if final:
                batches.append(BatchSpec(batch_id="Final", wave_ids=final))
                resolved.update(final)
                remaining.difference_update(final)
            break
        batches.append(BatchSpec(batch_id=batch_id, wave_ids=ready))
        resolved.update(ready)
        remaining.difference_update(ready)
        letter_ord += 1
        i += 1
    if any(w.wave_id.lower() == "final" for w in waves) and not any(
        b.batch_id == "Final" for b in batches
    ):
        final_id = next(w.wave_id for w in waves if w.wave_id.lower() == "final")
        batches.append(BatchSpec(batch_id="Final", wave_ids=[final_id]))
    elif not any(b.batch_id == "Final" for b in batches):
        batches.append(BatchSpec(batch_id="Final", wave_ids=[]))
    return batches


def build_graph_from_v1_dir(input_dir: Path, *, run_id: str) -> RunGraph:
    """Build a RunGraph from v1 wave-plan file(s) in *input_dir*."""
    wave_files = sorted(input_dir.glob("*-wave-plan.md"))
    if not wave_files:
        raise FileNotFoundError(f"No *-wave-plan.md files in {input_dir}")

    v1_plans = [parse_wave_plan_v1(f) for f in wave_files]
    primary = next(p for p in v1_plans if p.has_execution_graph)
    if not primary.has_execution_graph:
        raise ValueError("No v1 execution graph found")

    plan_meta = [parse_plan_file(f) for f in wave_files]
    graph = RunGraph(run_id=run_id, source_mode="B")
    lane_id = primary.plan_id
    lane = Lane(lane_id=lane_id, owned_paths=primary.owned_paths, plans=[lane_id])
    graph.lanes[lane_id] = lane

    node_id_map: dict[str, str] = {}
    for spec in primary.waves:
        node_id = f"{lane_id}:{spec.wave_id}"
        node_id_map[spec.wave_id] = node_id
        node = WaveNode(
            node_id=node_id,
            plan_id=lane_id,
            plan_file=primary.plan_file.name,
            wave_id=spec.wave_id,
            lane=primary.title,
            owned_paths=primary.owned_paths,
            forbidden_paths=[],
            effort=spec.effort,
            wall_clock_limit_s=_effort_seconds(spec.effort),
            depends_on=[node_id_map[d] for d in spec.depends_on if d in node_id_map],
            is_review_gate=spec.review_gate,
            verify_targets=list(spec.verify_targets),
            model=spec.model,
            role=spec.role,
        )
        graph.nodes[node_id] = node
        lane.waves.append(node)

    for node in graph.nodes.values():
        node.forbidden_paths = derive_forbidden_paths(lane_id, graph.lanes, node=node)

    batch_specs = primary.batches or _infer_batches_from_waves(primary.waves)
    for bs in batch_specs:
        lane_ids_for_batch: list[str] = []
        if bs.wave_ids:
            lane_ids_for_batch = [lane_id]
        cw = batch_cw_seams(bs.batch_id)
        label = bs.batch_id
        if bs.wave_ids:
            label = f"{bs.batch_id} — {', '.join(bs.wave_ids)}"
        if bs.human_gate:
            label = "HUMAN GATE — operator decisions"
        graph.batches.append(
            Batch(
                batch_id=bs.batch_id,
                label=label,
                lanes=lane_ids_for_batch,
                is_human_gate=bs.human_gate,
                gate_commands=["make ci-resume"] if bs.batch_id == "Final" else [],
                cw_seams=cw,
                merge_order=lane_ids_for_batch,
                wave_ids=list(bs.wave_ids),
            )
        )

    graph.pre0_gates = collect_pre0_gates_from_plans(plan_meta)
    if not graph.pre0_gates:
        graph.pre0_gates = [
            f"{w.wave_id}: {w.title} — review gate" for w in primary.waves if w.review_gate
        ]
    return attach_orchestrator_config(
        graph,
        input_dir,
        slug=primary.plan_id,
        wave_plan_text=primary.plan_file.read_text(),
    )
