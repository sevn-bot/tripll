"""tripll.parse.plan_files — Mode B parser (plain wave files → RunGraph).

Given a folder of plain ``*-wave-plan.md`` files, derive owned paths and
dependencies from each file, cluster path-disjoint plans into lanes, infer a
dependency-safe batch order, **write a generated ``parallel-wave.md``**, then
hand off to the Mode A parser (:mod:`tripll.parse.parallel_wave`).

CW-seam ownership (D10): an optional ``review-hints.yaml`` sidecar maps CW ids
to owning lanes (Option B). When absent, every lane forbids all CW hotspots
(Option A fallback).

Exports:
    PlanMeta — parsed metadata for one plain wave-plan file.
    read_review_hints — read ``cw_owners`` from ``review-hints.yaml``.
    parse_plan_file — parse one wave-plan file into a ``PlanMeta``.
    cluster_lanes — group path-overlapping plans into named lanes.
    generate_manifest — emit a ``parallel-wave.md`` from clustered lanes.
    build_graph_mode_b — full Mode B pipeline → RunGraph.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from tripll.graph import RunGraph, derive_forbidden_paths, paths_overlap
from tripll.parse.markdown import find_table_rows, strip_md
from tripll.parse.parallel_wave import build_run_graph

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class PlanMeta:
    """Parsed metadata for one plain wave-plan file.

    Args:
        plan_file (Path): Path to the wave-plan markdown file.
        plan_id (str): Slug derived from the filename.
        title (str): First ``#`` heading.
        owned_paths (list[str]): Paths from the ``Files in scope`` table.
        depends_on (list[str]): Plan numbers from a ``depends on`` header.
        effort (str): Effort marker (``S``/``M``/``L``/``XL``).
    """

    plan_file: Path
    plan_id: str
    title: str
    owned_paths: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    effort: str = "M"


def read_review_hints(input_dir: Path) -> dict[str, str]:
    """Read ``cw_owners`` from an optional ``review-hints.yaml`` sidecar (D10).

    Parses the minimal subset needed: a top-level ``cw_owners:`` block of
    ``CW-N: lane`` pairs. Returns an empty dict when the file is absent.

    Args:
        input_dir (Path): Directory that may contain ``review-hints.yaml``.

    Returns:
        dict[str, str]: ``CW-id → lane_id`` ownership map (possibly empty).

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as d:
        ...     _ = (Path(d) / "review-hints.yaml").write_text(
        ...         "cw_owners:\\n  CW-1: telemetry\\n")
        ...     read_review_hints(Path(d))
        {'CW-1': 'telemetry'}
    """
    path = input_dir / "review-hints.yaml"
    if not path.exists():
        return {}
    owners: dict[str, str] = {}
    in_block = False
    for line in path.read_text().splitlines():
        if re.match(r"^\s*cw_owners\s*:", line):
            in_block = True
            continue
        if in_block:
            if line.strip() and not line.startswith((" ", "\t")):
                break
            m = re.match(r"\s+(CW-\d+)\s*:\s*([^\s#]+)", line)
            if m:
                owners[m.group(1)] = m.group(2)
    return owners


def _slug(path: Path) -> str:
    """Return a short plan slug from a wave-plan filename.

    Args:
        path (Path): Wave-plan file path.

    Returns:
        str: Filename stem with the ``-wave-plan`` suffix removed.

    Examples:
        >>> _slug(Path("provider-runtime-telemetry-wave-plan.md"))
        'provider-runtime-telemetry'
    """
    return re.sub(r"-wave-plan$", "", path.stem)


_PATH_EXT_RE = re.compile(r"\.(py|json|md|yaml|yml|js|ts|tsx|toml)$", re.IGNORECASE)


def _is_owned_path(token: str) -> bool:
    """Return True when *token* looks like a repo file or directory path."""
    cleaned = token.strip().strip("`")
    if not cleaned or cleaned.startswith(("specs/", "prd/", "…")):
        return False
    if "/" in cleaned:
        return True
    return bool(_PATH_EXT_RE.search(cleaned))


def _parse_files_in_scope(text: str) -> list[str]:
    """Extract owned paths from a ``## Files in scope`` table."""
    paths: list[str] = []
    seen: set[str] = set()
    in_section = False
    for line in text.splitlines():
        if re.match(r"^##\s+Files in scope", line):
            in_section = True
            continue
        if in_section and re.match(r"^##\s+", line):
            break
    if not in_section:
        return paths
    # Re-scan only the section's table via the generic helper on the slice.
    section = _slice_section(text, "Files in scope")
    for cells in find_table_rows(section, ["Subsystem", "Paths"]):
        if len(cells) < 2:
            continue
        for token in re.findall(r"`([^`]+)`", cells[-1]):
            cleaned = token.strip()
            if _is_owned_path(cleaned) and cleaned not in seen:
                paths.append(cleaned)
                seen.add(cleaned)
    return paths


def _slice_section(text: str, heading_substr: str) -> str:
    """Return the text of the ``##`` section whose heading contains *heading_substr*."""
    lines = text.splitlines()
    out: list[str] = []
    in_section = False
    for line in lines:
        if re.match(r"^##\s+", line):
            if in_section:
                break
            if heading_substr in line:
                in_section = True
                continue
        if in_section:
            out.append(line)
    return "\n".join(out)


def _parse_depends_on(text: str) -> list[str]:
    """Extract plan-number dependencies from a ``depends on`` header line."""
    for line in text.splitlines()[:30]:
        m = re.search(r"depends\s+on[:\s]+(.+)", line, re.IGNORECASE)
        if m:
            return re.findall(r"#(\d+)", m.group(1))
    return []


def parse_plan_file(path: Path) -> PlanMeta:
    """Parse one plain wave-plan file into a :class:`PlanMeta`.

    Args:
        path (Path): Path to a ``*-wave-plan.md`` file.

    Returns:
        PlanMeta: Parsed metadata.

    Examples:
        >>> callable(parse_plan_file)
        True
    """
    text = path.read_text()
    title_m = re.search(r"^#\s+(.+)", text, re.MULTILINE)
    effort_m = re.search(r"effort[:\s]+([SMXL/\-]+)", text, re.IGNORECASE)
    return PlanMeta(
        plan_file=path,
        plan_id=_slug(path),
        title=title_m.group(1).strip() if title_m else _slug(path),
        owned_paths=_parse_files_in_scope(text),
        depends_on=_parse_depends_on(text),
        effort=(effort_m.group(1).strip() if effort_m else "M"),
    )


def cluster_lanes(plans: list[PlanMeta]) -> dict[str, list[PlanMeta]]:
    """Cluster plans into lanes by path-disjointness.

    Plans whose owned paths overlap share a lane. Lane names derive from the
    sole plan's slug (single-plan lane) or a shared path component.

    Args:
        plans (list[PlanMeta]): Parsed plans.

    Returns:
        dict[str, list[PlanMeta]]: ``lane_name → [PlanMeta, ...]``.

    Examples:
        >>> callable(cluster_lanes)
        True
    """
    groups: list[list[PlanMeta]] = []
    for plan in plans:
        placed = False
        for group in groups:
            if any(paths_overlap(plan.owned_paths, e.owned_paths) for e in group):
                group.append(plan)
                placed = True
                break
        if not placed:
            groups.append([plan])

    named: dict[str, list[PlanMeta]] = {}
    for i, group in enumerate(groups):
        if len(group) == 1:
            lane_name = group[0].plan_id.replace("-", " ").title()
        else:
            first = group[0].owned_paths
            if first and "/" in first[0]:
                parts = first[0].split("/")
                lane_name = (parts[2] if len(parts) > 2 else parts[-1]).replace("_", " ").title()
            else:
                lane_name = f"Lane {i}"
        # Disambiguate collisions.
        base = lane_name
        n = 2
        while lane_name in named:
            lane_name = f"{base} {n}"
            n += 1
        named[lane_name] = group
    return named


def _assign_batches(lanes: dict[str, list[PlanMeta]]) -> list[tuple[str, list[str]]]:
    """Return ``[(batch_id, [lane_names])]`` in dependency-safe order."""
    num_to_lane: dict[str, str] = {}
    plan_num = 1
    for lane_name, plans in lanes.items():
        for _ in plans:
            num_to_lane[str(plan_num)] = lane_name
            plan_num += 1

    lane_deps: dict[str, set[str]] = {ln: set() for ln in lanes}
    for lane_name, plans in lanes.items():
        for p in plans:
            for dep_num in p.depends_on:
                dep_lane = num_to_lane.get(dep_num)
                if dep_lane and dep_lane != lane_name:
                    lane_deps[lane_name].add(dep_lane)

    resolved: list[str] = []
    remaining = set(lanes)
    batches: list[tuple[str, list[str]]] = [("Pre-0", [])]
    letter = "A"
    guard = len(lanes) + 2
    i = 0
    while remaining and i < guard:
        ready = sorted(ln for ln in remaining if lane_deps[ln].issubset(set(resolved)))
        if not ready:
            ready = sorted(remaining)
        batches.append((letter, ready))
        resolved.extend(ready)
        remaining.difference_update(ready)
        letter = chr(ord(letter) + 1)
        i += 1
    batches.append(("Final", []))
    return batches


def generate_manifest(
    lanes: dict[str, list[PlanMeta]],
    batches: list[tuple[str, list[str]]],
    output_path: Path,
) -> None:
    """Write a generated ``parallel-wave.md`` from clustered lanes.

    Args:
        lanes (dict[str, list[PlanMeta]]): Clustered lanes.
        batches (list[tuple[str, list[str]]]): Batch order from
            :func:`_assign_batches`.
        output_path (Path): Destination ``parallel-wave.md`` path.

    Examples:
        >>> callable(generate_manifest)
        True
    """
    out: list[str] = [
        "# Generated parallel-wave manifest (Mode B)\n\n",
        "**Generated by:** tripll.parse.plan_files\n\n---\n\n",
        "## Plan index\n\n| # | Plan | Effort | Lane |\n|---|------|--------|------|\n",
    ]
    num = 1
    for lane_name, plans in lanes.items():
        for plan in plans:
            out.append(
                f"| {num} | [{plan.plan_id}]({plan.plan_file.name}) "
                f"| {plan.effort} | **{lane_name}** |\n"
            )
            num += 1
    out.append("\n---\n\n## Phase diagram\n\n```\n")
    for batch_id, names in batches:
        if batch_id == "Pre-0":
            out.append("Phase Pre-0 — HUMAN GATE\n")
        elif batch_id == "Final":
            out.append("Phase Final — make ci-resume\n")
        else:
            out.append(f"Phase {batch_id} — {', '.join(names) or '(empty)'}\n")
    out.append("```\n\n---\n\n")
    out.append("## Parallel lanes (disjoint file ownership)\n\n")
    out.append("| Lane | Plans | Owned paths (do not cross-edit) |\n")
    out.append("|------|-------|---------------------------------|\n")
    num = 1
    for lane_name, plans in lanes.items():
        refs = ", ".join(f"#{num + i}" for i in range(len(plans)))
        all_paths: list[str] = []
        for p in plans:
            all_paths.extend(p.owned_paths)
        paths_str = ", ".join(f"`{p}`" for p in all_paths)
        out.append(f"| **{lane_name}** | {refs} | {paths_str} |\n")
        num += len(plans)
    out.append(
        "\n---\n\n## Hard dependencies\n\n| Consumer | Requires |\n|----------|----------|\n"
    )
    for plans in lanes.values():
        for plan in plans:
            for dep in plan.depends_on:
                out.append(f"| {plan.plan_id} | #{dep} |\n")
    out.append("\n")
    output_path.write_text("".join(out))


def collect_pre0_gates_from_plans(plans: list[PlanMeta]) -> list[str]:
    """Derive Pre-0 gate items from plain wave-plan files (Mode B, D10).

    Scans each plan for a ``## Wave W0`` review section and decision-table rows
    that require W0 operator confirmation. Does **not** inject dev_eval gates.

    Args:
        plans (list[PlanMeta]): Parsed wave-plan files in the input set.

    Returns:
        list[str]: Gate descriptions for the Pre-0 human sheet (may be empty).

    Examples:
        >>> collect_pre0_gates_from_plans([])
        []
    """
    gates: list[str] = []
    seen: set[str] = set()
    for plan in plans:
        text = plan.plan_file.read_text()
        for cells in find_table_rows(text, ["Topic", "Decision"]):
            if len(cells) < 2:
                continue
            topic = strip_md(cells[0])
            decision = cells[1].strip()
            if re.search(r"confirm at W0|W0 review", decision, re.IGNORECASE):
                gate = f"{topic}: {strip_md(decision)}"
                if gate not in seen:
                    gates.append(gate)
                    seen.add(gate)
        if re.search(r"^## Wave W0\b", text, re.MULTILINE | re.IGNORECASE):
            w0 = _slice_section(text, "Wave W0")
            for line in w0.splitlines():
                if re.search(r"review gate", line, re.IGNORECASE):
                    gate = f"{plan.plan_id}: {strip_md(line)}"
                    if gate not in seen:
                        gates.append(gate)
                        seen.add(gate)
            if not any(plan.plan_id in g for g in gates):
                gate = (
                    f"{plan.plan_id}: Wave W0 review gate — "
                    "operator sign-off before implementation waves"
                )
                gates.append(gate)
                seen.add(gate)
    return gates


def build_graph_mode_b(input_dir: Path, *, run_id: str) -> RunGraph:
    """Run the full Mode B pipeline and return a :class:`RunGraph`.

    Parses every ``*-wave-plan.md`` in *input_dir*, clusters lanes, writes a
    generated ``parallel-wave.md``, builds the graph via Mode A, then applies
    CW ownership from ``review-hints.yaml`` to each node's forbidden set (D10).

    Args:
        input_dir (Path): Folder of plain wave-plan files.
        run_id (str): Run identifier.

    Returns:
        RunGraph: The derived run graph (``source_mode == 'B'``).

    Raises:
        FileNotFoundError: If no ``*-wave-plan.md`` files are found.

    Examples:
        >>> callable(build_graph_mode_b)
        True
    """
    wave_files = sorted(input_dir.glob("*-wave-plan.md"))
    if not wave_files:
        raise FileNotFoundError(f"No *-wave-plan.md files found in {input_dir}")

    plans = [parse_plan_file(f) for f in wave_files]
    lanes = cluster_lanes(plans)
    batches = _assign_batches(lanes)

    manifest = input_dir / "parallel-wave.md"
    generate_manifest(lanes, batches, manifest)

    pre0_gates = collect_pre0_gates_from_plans(plans)
    graph = build_run_graph(
        manifest.read_text(),
        None,
        None,
        run_id=run_id,
        batch_assignments=batches,
        pre0_gates_override=pre0_gates,
    )
    graph.source_mode = "B"

    cw_owners = read_review_hints(input_dir)
    for node in graph.nodes.values():
        lane_id = node.plan_id
        node.forbidden_paths = derive_forbidden_paths(lane_id, graph.lanes, cw_owners=cw_owners)

    wave_text = wave_files[0].read_text() if wave_files else None
    slug = plans[0].plan_id if plans else None
    from tripll.parse.orchestrator_prompt import attach_orchestrator_config

    return attach_orchestrator_config(
        graph,
        input_dir,
        slug=slug,
        wave_plan_text=wave_text,
    )
