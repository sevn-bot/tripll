"""tripll.graph — RunGraph data model and validation.

Defines the dataclasses that model one orchestration run (``WaveNode``,
``Lane``, ``Batch``, ``RunGraph``) plus the coordination-wave (CW) hotspot
table and the ``RunGraph.validate`` checks (cycle detection, owned-path
overlap, dangling dependency, unknown CW seam).

The data model mirrors ``wave-orchestrator/docs/design-note.md`` §1.

Exports:
    CW_HOTSPOTS — coordination-wave hotspot path map (CW-1 … CW-5).
    ALL_CW_PATHS — flattened list of every CW hotspot path.
    paths_overlap — True when two owned-path sets share or nest a path.
    OrchestratorConfig — optional orchestrator-mode settings (design-note §8.6).
    WaveNode — atomic unit of work (one wave of one plan).
    Lane — group of disjoint plans sharing owned paths.
    Batch — group of lanes that may run in parallel.
    RunGraph — top-level execution graph with ``validate`` + ``to_dict``.
    derive_forbidden_paths — compute a lane's forbidden-path set (CW + others).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# ---------------------------------------------------------------------------
# Coordination-wave hotspot paths (design-note.md §2.1)
# ---------------------------------------------------------------------------


def _load_cw_hotspots() -> dict[str, list[str]]:
    from tripll.plan.cw_buckets import default_cw_hotspots

    return default_cw_hotspots()


CW_HOTSPOTS: dict[str, list[str]] = _load_cw_hotspots()

ALL_CW_PATHS: list[str] = [p for paths in CW_HOTSPOTS.values() for p in paths]


# ---------------------------------------------------------------------------
# Path-overlap helper
# ---------------------------------------------------------------------------


def paths_overlap(a: list[str], b: list[str]) -> bool:
    """Return True when any path in *a* equals or nests any path in *b*.

    Comparison is prefix-based after stripping trailing slashes: ``foo/`` and
    ``foo/bar.py`` overlap; ``foo`` and ``foobar`` do not.

    Args:
        a (list[str]): First owned-path set.
        b (list[str]): Second owned-path set.

    Returns:
        bool: True if the two sets are not disjoint.

    Examples:
        >>> paths_overlap(["src/a/"], ["src/a/x.py"])
        True
        >>> paths_overlap(["src/a"], ["src/b"])
        False
    """
    for pa in a:
        pa2 = pa.rstrip("/")
        for pb in b:
            pb2 = pb.rstrip("/")
            if pa2 == pb2:
                return True
            if pa2.startswith(pb2 + "/") or pb2.startswith(pa2 + "/"):
                return True
    return False


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class WaveNode:
    """Atomic unit of work — a single wave from a single plan.

    Args:
        node_id (str): ``<plan_id>:<wave_id>`` composite key.
        plan_id (str): Short plan slug.
        plan_file (str): Path to the wave-plan markdown file.
        wave_id (str): Exact heading label (e.g. ``'W1'``).
        lane (str): Logical lane name.
        owned_paths (list[str]): Paths this wave may edit.
        forbidden_paths (list[str]): Paths this wave must not edit.
        effort (str): ``'S'`` | ``'M'`` | ``'L'`` | ``'XL'``.
        wall_clock_limit_s (int): Wall-clock limit in seconds.
        depends_on (list[str]): node_ids this wave must follow.
        is_review_gate (bool): True for human-gated review waves.
        verify_targets (list[str]): make targets to run after dispatch.
        docs_menu_sync (list[str]): make targets for Docs&Menu sync.
    """

    node_id: str
    plan_id: str
    plan_file: str
    wave_id: str
    lane: str
    owned_paths: list[str] = field(default_factory=list)
    forbidden_paths: list[str] = field(default_factory=list)
    effort: str = "M"
    wall_clock_limit_s: int = 2700
    depends_on: list[str] = field(default_factory=list)
    is_review_gate: bool = False
    verify_targets: list[str] = field(default_factory=lambda: ["make ci-affected"])
    docs_menu_sync: list[str] = field(default_factory=list)
    model: str | None = None
    role: str = "impl"


@dataclass
class Lane:
    """Group of disjoint plans sharing owned paths on one branch.

    Args:
        lane_id (str): Sanitised lane identifier.
        plans (list[str]): plan_ids in this lane.
        owned_paths (list[str]): Paths disjoint from all other lanes.
        waves (list[WaveNode]): Ordered waves in this lane.
    """

    lane_id: str
    plans: list[str] = field(default_factory=list)
    owned_paths: list[str] = field(default_factory=list)
    waves: list[WaveNode] = field(default_factory=list)


@dataclass
class OrchestratorConfig:
    """Orchestrator-mode settings when ``*-orchestrator-prompt.md`` is present.

    Locked shape from design-note §8.6 (tripll orchestrator-mode plan W0.3).

    Args:
        enabled (bool): True when orchestrator mode is active.
        prompt_path (str): Path to the orchestrator prompt file.
        feature_branch (str | None): Single integration branch (D8).
        single_branch (bool): Force one worktree on ``feature_branch``.
        commit_per_wave (bool): Commit+push after each wave verify (D7).
        verify_target (str): Makefile target from repo root (default ``partial-ci``).
        ci_base (str): ``SEVN_CI_BASE`` value (default ``origin/test-pre``).
        serial_waves (list[str]): Ordered wave ids from the prompt.
        review_gates (dict[str, str]): wave_id → gate label (e.g. ``W0.8``).
        commit_subjects (dict[str, str]): wave_id → commit subject from prompt table.
        model_policy (str): ``inherit`` | ``auto`` (D11).
        agent_wave (str): Subagent for wave dispatch (default ``wave-runner``).
        agent_orchestrator (str): Subagent for review gates (default ``wave-orchestrator``).
        role_dispatch (bool): Enable per-role agent injection (design-note §10.4).
    """

    enabled: bool
    prompt_path: str
    feature_branch: str | None = None
    single_branch: bool = True
    commit_per_wave: bool = True
    verify_target: str = "partial-ci"
    ci_base: str = "origin/test-pre"
    serial_waves: list[str] = field(default_factory=list)
    review_gates: dict[str, str] = field(default_factory=dict)
    commit_subjects: dict[str, str] = field(default_factory=dict)
    model_policy: str = "inherit"
    agent_wave: str = "wave-runner"
    agent_orchestrator: str = "wave-orchestrator"
    agent_test: str = "test-creator"
    role_dispatch: bool = False


@dataclass
class Batch:
    """Group of lanes that may run in parallel.

    Args:
        batch_id (str): ``'Pre-0'`` | ``'A'`` … | ``'Final'``.
        label (str): Human-readable label.
        lanes (list[str]): lane_ids in this batch.
        is_human_gate (bool): True for Pre-0 / review-gate batches.
        gate_commands (list[str]): make targets to run at Batch Final.
        cw_seams (list[str]): CW ids that serialise within the batch.
        merge_order (list[str]): lane merge order at Batch Final.
        wave_ids (list[str]): wave_id labels in this batch (v1 single-plan sets).
    """

    batch_id: str
    label: str
    lanes: list[str] = field(default_factory=list)
    is_human_gate: bool = False
    gate_commands: list[str] = field(default_factory=list)
    cw_seams: list[str] = field(default_factory=list)
    merge_order: list[str] = field(default_factory=list)
    wave_ids: list[str] = field(default_factory=list)


@dataclass
class RunGraph:
    """Top-level execution graph for one run.

    Args:
        run_id (str): Run identifier.
        source_mode (Literal["A", "B"]): Parse mode.
        batches (list[Batch]): Ordered Pre-0 → … → Final.
        lanes (dict[str, Lane]): lane_id → Lane.
        nodes (dict[str, WaveNode]): node_id → WaveNode.
        pre0_gates (list[str]): Gate items collected at Pre-0.
        cw_seams (dict[str, list[str]]): CW id → node_ids serialised on it.
        orchestrator (OrchestratorConfig | None): Orchestrator mode config (W1).
        role_dispatch (bool): Plan-level role-dispatch toggle (design-note §10.4).
    """

    run_id: str
    source_mode: Literal["A", "B"] = "A"
    batches: list[Batch] = field(default_factory=list)
    lanes: dict[str, Lane] = field(default_factory=dict)
    nodes: dict[str, WaveNode] = field(default_factory=dict)
    pre0_gates: list[str] = field(default_factory=list)
    cw_seams: dict[str, list[str]] = field(default_factory=dict)
    orchestrator: OrchestratorConfig | None = None
    role_dispatch: bool = False

    def batch_order(self) -> list[str]:
        """Return the ordered list of batch ids.

        Returns:
            list[str]: Batch ids in execution order.

        Examples:
            >>> g = RunGraph(run_id="r", batches=[Batch("Pre-0", "gate"), Batch("Final", "f")])
            >>> g.batch_order()
            ['Pre-0', 'Final']
        """
        return [b.batch_id for b in self.batches]

    def validate(self) -> list[str]:
        """Return a list of validation errors (empty list = valid).

        Checks performed:

        1. **Dangling dependency** — a node's ``depends_on`` references a
           node not present in :attr:`nodes`.
        2. **Cycle detection** — the node dependency graph contains a cycle.
        3. **Owned-path overlap** — two distinct lanes share an owned path.
        4. **Unknown CW seam** — a batch references a CW id absent from
           :data:`CW_HOTSPOTS`.

        Returns:
            list[str]: Human-readable error strings; empty when valid.

        Examples:
            >>> g = RunGraph(run_id="r")
            >>> g.validate()
            []
        """
        errors: list[str] = []
        errors.extend(self._check_dangling_deps())
        errors.extend(self._check_cycles())
        errors.extend(self._check_overlaps())
        errors.extend(self._check_cw_seams())
        return errors

    def _check_dangling_deps(self) -> list[str]:
        errors: list[str] = []
        for node in self.nodes.values():
            for dep in node.depends_on:
                if dep not in self.nodes:
                    errors.append(f"dangling dependency: {node.node_id} → {dep} (missing node)")
        return errors

    def _check_cycles(self) -> list[str]:
        # DFS-based cycle detection over depends_on edges (ignore dangling).
        WHITE, GREY, BLACK = 0, 1, 2
        color: dict[str, int] = {nid: WHITE for nid in self.nodes}
        errors: list[str] = []

        def visit(nid: str, stack: list[str]) -> None:
            color[nid] = GREY
            stack.append(nid)
            for dep in self.nodes[nid].depends_on:
                if dep not in self.nodes:
                    continue
                if color[dep] == GREY:
                    cycle = [*stack[stack.index(dep) :], dep]
                    errors.append("cycle detected: " + " → ".join(cycle))
                elif color[dep] == WHITE:
                    visit(dep, stack)
            stack.pop()
            color[nid] = BLACK

        for nid in self.nodes:
            if color[nid] == WHITE:
                visit(nid, [])
        return errors

    def _check_overlaps(self) -> list[str]:
        errors: list[str] = []
        lane_items = list(self.lanes.items())
        for i in range(len(lane_items)):
            id_a, lane_a = lane_items[i]
            for j in range(i + 1, len(lane_items)):
                id_b, lane_b = lane_items[j]
                if paths_overlap(lane_a.owned_paths, lane_b.owned_paths):
                    errors.append(f"owned-path overlap: lane {id_a!r} and lane {id_b!r}")
        return errors

    def _check_cw_seams(self) -> list[str]:
        errors: list[str] = []
        for batch in self.batches:
            for cw in batch.cw_seams:
                if cw not in CW_HOTSPOTS:
                    errors.append(f"unknown CW seam {cw!r} in batch {batch.batch_id!r}")
        return errors

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable dict of the graph.

        Returns:
            dict[str, object]: Plain-dict representation suitable for
            ``json.dumps`` and persistence in ``graph.json``.

        Examples:
            >>> g = RunGraph(run_id="r")
            >>> g.to_dict()["run_id"]
            'r'
        """
        out: dict[str, object] = {
            "run_id": self.run_id,
            "source_mode": self.source_mode,
            "batches": [vars(b) for b in self.batches],
            "lanes": {
                lid: {
                    "lane_id": lane.lane_id,
                    "plans": lane.plans,
                    "owned_paths": lane.owned_paths,
                    "waves": [vars(w) for w in lane.waves],
                }
                for lid, lane in self.lanes.items()
            },
            "nodes": {nid: vars(n) for nid, n in self.nodes.items()},
            "pre0_gates": self.pre0_gates,
            "cw_seams": self.cw_seams,
            "role_dispatch": self.role_dispatch,
        }
        if self.orchestrator is not None:
            out["orchestrator"] = vars(self.orchestrator)
        return out


# ---------------------------------------------------------------------------
# Forbidden-path derivation (W2.4)
# ---------------------------------------------------------------------------

#: Test-owned roots forbidden to every non-``test-author`` wave (design-note
#: §9.2). The ``test-creator`` agent is the single owner of these paths; impl
#: waves must never edit tests, so the node-level overlay in
#: :func:`derive_forbidden_paths` adds these to an impl node's forbidden set.
TEST_PATHS: list[str] = ["tests/", "wave-orchestrator/tests/"]


def derive_forbidden_paths(
    lane_id: str,
    lanes: dict[str, Lane],
    *,
    cw_owners: dict[str, str] | None = None,
    node: WaveNode | None = None,
) -> list[str]:
    """Compute the forbidden-path set for *lane_id*.

    The forbidden set is every other lane's owned paths plus the CW hotspot
    paths the lane does not own. When *cw_owners* maps a CW id to *lane_id*,
    that lane's hotspot paths are excluded from its forbidden set (D10
    Option B); otherwise all CW hotspots are forbidden (Option A fallback).

    When *node* is supplied, a node-level overlay applies the tests-first model
    (design-note §9.2): every node whose ``role`` is not ``test-author`` also
    forbids :data:`TEST_PATHS` (even when the lane owns them), while a
    ``test-author`` node — the sole test owner — does not.

    Args:
        lane_id (str): The lane whose forbidden set is computed.
        lanes (dict[str, Lane]): All lanes in the graph.
        cw_owners (dict[str, str] | None): Optional ``CW-id → lane_id`` map.
        node (WaveNode | None): When set, apply the role-based TEST_PATHS overlay.

    Returns:
        list[str]: Sorted, de-duplicated forbidden paths.

    Examples:
        >>> lanes = {"a": Lane("a", owned_paths=["src/a/"]), "b": Lane("b", owned_paths=["src/b/"])}
        >>> "src/b/" in derive_forbidden_paths("a", lanes)
        True
    """
    owners = cw_owners or {}
    forbidden: set[str] = set()

    for other_id, other in lanes.items():
        if other_id != lane_id:
            forbidden.update(other.owned_paths)

    owned = lanes[lane_id].owned_paths if lane_id in lanes else []

    for cw, paths in CW_HOTSPOTS.items():
        if owners.get(cw) == lane_id:
            continue
        for path in paths:
            if paths_overlap(owned, [path]):
                continue
            forbidden.add(path)

    if node is not None and node.role != "test-author":
        owned = node.owned_paths or (lanes[lane_id].owned_paths if lane_id in lanes else [])
        for test_root in TEST_PATHS:
            if paths_overlap(owned, [test_root]):
                continue
            forbidden.add(test_root)

    return sorted(forbidden)
