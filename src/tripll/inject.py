"""Live hotfix injection, parallel lane add, and graph↔ledger reconciliation.

Exports:
    HotfixTask — immutable hotfix inject spec persisted under ``injects/``.
    WaveAddTask — structured parallel-lane wave inject spec.
    ReconcileResult — outcome of :func:`reconcile_run_graph`.
    InjectError — validation failure with CLI exit code.
    resolve_after_node_id — map ``--after`` to a graph node id.
    validate_hotfix_inject — pause/scope/deps/cost checks.
    plan_hotfix_inject — build hotfix task + merged graph without persisting.
    apply_hotfix_inject — write hotfix audit artefact, ledger row, graph.json.
    plan_wave_add — build wave-add task + merged graph without persisting.
    apply_wave_add — write wave-add audit artefact, ledger row, graph.json.
    merge_injected_artefacts — re-apply inject artefacts after plan re-parse.
    merge_injected_hotfixes — alias for hotfix-only merge (backward compat).
    reconcile_run_graph — diff parsed graph vs ledger; seed new waves safely.
    load_hotfix_tasks — read hotfix inject specs from a run directory.
    load_wave_add_tasks — read wave-add inject specs from a run directory.
"""

from __future__ import annotations

from tripll.inject_dispatch import (
    HotfixTask,
    InjectError,
    ReconcileResult,
    WaveAddTask,
    apply_hotfix_inject,
    apply_wave_add,
    load_hotfix_tasks,
    load_wave_add_tasks,
    merge_injected_artefacts,
    merge_injected_hotfixes,
    plan_hotfix_inject,
    plan_wave_add,
    reconcile_run_graph,
    resolve_after_node_id,
    validate_hotfix_inject,
)

__all__ = [
    "HotfixTask",
    "InjectError",
    "ReconcileResult",
    "WaveAddTask",
    "apply_hotfix_inject",
    "apply_wave_add",
    "load_hotfix_tasks",
    "load_wave_add_tasks",
    "merge_injected_artefacts",
    "merge_injected_hotfixes",
    "plan_hotfix_inject",
    "plan_wave_add",
    "reconcile_run_graph",
    "resolve_after_node_id",
    "validate_hotfix_inject",
]
