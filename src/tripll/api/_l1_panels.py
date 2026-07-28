"""Dashboard panels for code factory L1 — graph, findings, exits (§12)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tripll.github.findings import list_findings_from_store
from tripll.graphstore import SqliteGraphStore
from tripll.loops.exits import DEFAULT_BUDGET_USD, DEFAULT_MAX_TURNS, EXIT_NAMES

if TYPE_CHECKING:
    from tripll.ledger import WaveRow

__all__ = [
    "ExitCapRow",
    "FindingsPanelView",
    "GraphPanelView",
    "L1PanelsView",
    "build_exits_panel",
    "build_findings_panel",
    "build_graph_panel",
    "build_l1_panels",
    "resolve_graph_db",
]


@dataclass(frozen=True, slots=True)
class GraphPanelView:
    """Wave subgraph summary for the dashboard."""

    available: bool
    wave_id: str
    node_id: str
    db_path: str
    node_count: int
    edge_count: int
    sample_nodes: list[dict[str, str]] = field(default_factory=list)
    message: str = ""


@dataclass(frozen=True, slots=True)
class FindingsPanelView:
    """Findings grouped by state."""

    available: bool
    groups: dict[str, list[dict[str, Any]]]
    total: int
    message: str = ""


@dataclass(frozen=True, slots=True)
class ExitCapRow:
    """One exit cap with proximity to firing."""

    exit_id: int
    name: str
    label: str
    current: str
    cap: str
    ratio: float
    near: bool


@dataclass(frozen=True, slots=True)
class L1PanelsView:
    """Combined L1 dashboard panels."""

    graph: GraphPanelView
    findings: FindingsPanelView
    exits: list[ExitCapRow]


def resolve_graph_db(*, run_dir: Path | None, repo_root: Path | None = None) -> Path | None:
    """Return the graph database path when present."""
    candidates: list[Path] = []
    if run_dir is not None:
        candidates.append(run_dir / ".tripll" / "graph.db")
    if repo_root is not None:
        candidates.append(repo_root / ".tripll" / "graph.db")
    candidates.append(Path(".tripll/graph.db"))
    for path in candidates:
        if path.is_file():
            return path.resolve()
    return None


def _pick_focus_wave(waves: list[WaveRow]) -> WaveRow | None:
    priority = (
        "running",
        "quality_loop",
        "verifying",
        "dispatched",
        "unverified",
        "failed",
        "blocked",
    )
    by_state = {w.node_id: w for w in waves}
    for state in priority:
        for wave in waves:
            if wave.state == state:
                return wave
    return next(iter(by_state.values()), None) if by_state else None


def _wave_targets(run_dir: Path | None, wave: WaveRow) -> list[str]:
    if run_dir is None:
        return []
    graph_path = run_dir / "graph.json"
    if not graph_path.is_file():
        return []
    try:
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    node = (graph.get("nodes") or {}).get(wave.node_id) or {}
    targets = node.get("owned_paths") or node.get("targets") or []
    return [str(t) for t in targets if t]


def build_graph_panel(
    *,
    run_dir: Path | None,
    waves: list[WaveRow],
    repo_root: Path | None = None,
) -> GraphPanelView:
    """Build the graph panel for the focus wave."""
    focus = _pick_focus_wave(waves)
    if focus is None:
        return GraphPanelView(
            available=False,
            wave_id="",
            node_id="",
            db_path="",
            node_count=0,
            edge_count=0,
            message="No waves in this run yet.",
        )
    db_path = resolve_graph_db(run_dir=run_dir, repo_root=repo_root)
    if db_path is None:
        return GraphPanelView(
            available=False,
            wave_id=focus.wave_id,
            node_id=focus.node_id,
            db_path="",
            node_count=0,
            edge_count=0,
            message="No `.tripll/graph.db` — run `tripll graph extract` on the target repo.",
        )
    targets = _wave_targets(run_dir, focus)
    sample: list[dict[str, str]] = []
    node_count = 0
    edge_count = 0
    store = SqliteGraphStore(str(db_path))
    try:
        if targets:
            from tripll.serve.brief_packer import SUBGRAPH_PREDICATES, _seeds_from_targets

            seeds = _seeds_from_targets(targets, store)
            subgraph = store.subgraph(
                seeds,
                hops=2,
                predicates=SUBGRAPH_PREDICATES,
                at_sha="HEAD",
            )
            node_count = len(subgraph.nodes)
            edge_count = len(subgraph.edges)
            for node in subgraph.nodes[:12]:
                sample.append(
                    {
                        "kind": node.kind,
                        "key": node.natural_key,
                        "layer": node.layer,
                    }
                )
        else:
            row = store.conn.execute("SELECT COUNT(*) FROM nodes WHERE valid_to IS NULL").fetchone()
            node_count = int(row[0]) if row else 0
            row = store.conn.execute("SELECT COUNT(*) FROM edges WHERE valid_to IS NULL").fetchone()
            edge_count = int(row[0]) if row else 0
            rows = store.conn.execute(
                """SELECT kind, natural_key, layer FROM nodes
                   WHERE valid_to IS NULL ORDER BY layer, kind LIMIT 12"""
            ).fetchall()
            for row in rows:
                sample.append({"kind": str(row[0]), "key": str(row[1]), "layer": str(row[2])})
    except OSError as exc:
        return GraphPanelView(
            available=False,
            wave_id=focus.wave_id,
            node_id=focus.node_id,
            db_path=str(db_path),
            node_count=0,
            edge_count=0,
            message=f"Graph store unreadable: {exc}",
        )
    finally:
        store.close()
    return GraphPanelView(
        available=True,
        wave_id=focus.wave_id,
        node_id=focus.node_id,
        db_path=str(db_path),
        node_count=node_count,
        edge_count=edge_count,
        sample_nodes=sample,
        message="",
    )


def build_findings_panel(
    *, run_dir: Path | None, repo_root: Path | None = None
) -> FindingsPanelView:
    """Group Finding nodes by state."""
    db_path = resolve_graph_db(run_dir=run_dir, repo_root=repo_root)
    if db_path is None:
        return FindingsPanelView(
            available=False,
            groups={},
            total=0,
            message="No graph store — findings appear after `tripll findings sync`.",
        )
    store = SqliteGraphStore(str(db_path))
    try:
        rows = list_findings_from_store(store)
    except OSError as exc:
        return FindingsPanelView(
            available=False,
            groups={},
            total=0,
            message=f"Could not load findings: {exc}",
        )
    finally:
        store.close()
    groups: dict[str, list[dict[str, Any]]] = {}
    for finding in rows:
        state = str(finding.get("state") or "open")
        groups.setdefault(state, []).append(
            {
                "finding_id": str(finding.get("finding_id") or finding.get("node_id") or "")[:12],
                "kind": str(finding.get("kind") or ""),
                "rule_id": str(finding.get("rule_id") or ""),
                "file": str(finding.get("file") or ""),
                "severity": str(finding.get("severity") or ""),
            }
        )
    for items in groups.values():
        items.sort(key=lambda item: (item["severity"], item["rule_id"]))
    return FindingsPanelView(
        available=True,
        groups=dict(sorted(groups.items())),
        total=len(rows),
        message="",
    )


def build_exits_panel(
    *,
    waves: list[WaveRow],
    run_cost: float,
    max_attempts: int = DEFAULT_MAX_TURNS,
    fired_exit_ids: list[int] | None = None,
) -> list[ExitCapRow]:
    """Show exit caps and proximity (§12 dashboard)."""
    budget = float(os.environ.get("TRIPLL_COST_BUDGET_USD") or DEFAULT_BUDGET_USD)
    peak_attempts = max((w.attempt_count for w in waves), default=0)
    blocked = sum(1 for w in waves if w.state == "blocked")
    unverified = sum(1 for w in waves if w.state == "unverified")
    fired = set(fired_exit_ids or [])

    def row(
        exit_id: int,
        label: str,
        current: str,
        cap: str,
        ratio: float,
    ) -> ExitCapRow:
        name = EXIT_NAMES[exit_id]
        return ExitCapRow(
            exit_id=exit_id,
            name=name,
            label=label,
            current=current,
            cap=cap,
            ratio=min(max(ratio, 0.0), 1.0),
            near=ratio >= 0.8,
        )

    attempt_ratio = peak_attempts / max_attempts if max_attempts else 0.0
    budget_ratio = run_cost / budget if budget > 0 else 0.0
    return [
        row(
            2,
            "Turn cap",
            "fired" if 2 in fired else str(peak_attempts),
            str(max_attempts),
            attempt_ratio,
        ),
        row(
            3,
            "Budget cap",
            "fired" if 3 in fired else f"${run_cost:.2f}",
            f"${budget:.2f}",
            budget_ratio,
        ),
        row(
            7,
            "Error threshold",
            "fired" if 7 in fired else str(blocked),
            "circuit breaker",
            min(blocked / 5.0, 1.0) if blocked else 0.0,
        ),
        row(
            1,
            "Goal met",
            "fired" if 1 in fired else "pending",
            "CI + pullfrog-approval",
            1.0 if 1 in fired else 0.0,
        ),
        row(
            5,
            "No progress",
            "fired" if 5 in fired else "—",
            "3 unchanged turns",
            1.0 if 5 in fired else 0.0,
        ),
        row(
            4,
            "Wall clock",
            "fired" if 4 in fired else f"{unverified} unverified",
            "per-wave limit",
            1.0 if 4 in fired else 0.0,
        ),
    ]


def build_l1_panels(
    *,
    run_dir: Path | None,
    waves: list[WaveRow],
    run_cost: float,
    repo_root: Path | None = None,
    fired_exit_ids: list[int] | None = None,
) -> L1PanelsView:
    """Build all three L1 dashboard panels."""
    return L1PanelsView(
        graph=build_graph_panel(run_dir=run_dir, waves=waves, repo_root=repo_root),
        findings=build_findings_panel(run_dir=run_dir, repo_root=repo_root),
        exits=build_exits_panel(
            waves=waves,
            run_cost=run_cost,
            fired_exit_ids=fired_exit_ids,
        ),
    )
