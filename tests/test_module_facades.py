"""Characterization tests for god-module façades (issue #16, wave plan W1).

Locks import-surface identity before W3-W8 extractions. Green at baseline except
``ledger.__all__`` completeness (xfail until W3).
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest
import typer
from typer.testing import CliRunner

import tripll.api.app as api_app
import tripll.cli as cli_pkg
import tripll.cli._run as cli_run
import tripll.engine as engine_mod
import tripll.ledger as ledger_mod
from tripll.api.app import create_app
from tripll.api.ui.router import make_ui_router
from tripll.cli import app as cli_app
from tripll.cli._run import register_run_commands, rewrite_run_inject_argv
from tripll.engine import (
    can_run_concurrently,
    human_gate_node_ids,
    nodes_for_batch,
    orchestrator_serial_nodes,
    ready_nodes,
    select_concurrent_set,
)
from tripll.engine_scheduling import (
    can_run_concurrently as scheduling_can_run_concurrently,
)
from tripll.engine_scheduling import (
    human_gate_node_ids as scheduling_human_gate_node_ids,
)
from tripll.engine_scheduling import (
    nodes_for_batch as scheduling_nodes_for_batch,
)
from tripll.engine_scheduling import (
    orchestrator_serial_nodes as scheduling_orchestrator_serial_nodes,
)
from tripll.engine_scheduling import (
    ready_nodes as scheduling_ready_nodes,
)
from tripll.engine_scheduling import (
    select_concurrent_set as scheduling_select_concurrent_set,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CLI_RUNNER = CliRunner()

# Baseline CLI inventory at 2e4a8f2 — registration order (hidden run-* after run).
EXPECTED_CLI_COMMANDS: tuple[str, ...] = (
    "run",
    "run-inject",
    "run-reconcile-graph",
    "setup",
    "doctor",
    "init",
    "new",
    "status",
    "list-runs",
    "pause",
    "resume",
    "approve",
    "delete-run",
    "reset-run",
    "pre0-interview",
    "validate",
    "validate-plan",
    "calibrate",
    "serve",
    "doc-score",
    "wave add",
    "plan publish",
    "graph extract",
    "graph fuse",
    "graph gate",
    "graph query",
    "findings sync",
    "findings list",
    "findings triage",
    "findings export-learnings",
    "rules derive",
    "rules list",
    "rules promote",
    "rules retire",
    "review diff",
    "review watch",
    "review init",
    "review dispatch",
    "bench run",
    "skw run",
    "skw pipeline-build",
    "skw pipeline-diagram",
    "skw pipeline-show",
    "skw next-step",
    "skw render",
    "skw agent-run",
    "spec validate",
    "spec score",
    "prd validate",
    "prd score",
    "changelog check",
    "changelog eval",
    "pr shepherd",
    "pr status",
    "pr approve-merge",
)

EXPECTED_CLI_GROUPS: tuple[str, ...] = (
    "wave",
    "plan",
    "graph",
    "findings",
    "rules",
    "review",
    "bench",
    "skw",
    "spec",
    "prd",
    "changelog",
    "pr",
)

# JSON routes from create_app() + UI routes from make_ui_router() at baseline.
EXPECTED_JSON_ROUTES: tuple[tuple[str, str], ...] = (
    ("GET", "/health"),
    ("GET", "/api/agents"),
    ("POST", "/api/agents"),
    ("GET", "/api/agents/{profile_id}"),
    ("PATCH", "/api/agents/{profile_id}"),
    ("DELETE", "/api/agents/{profile_id}"),
    ("GET", "/api/runs"),
    ("POST", "/api/runs"),
    ("GET", "/api/runs/{run_id}"),
    ("POST", "/api/runs/{run_id}/approve"),
    ("GET", "/api/runs/{run_id}/hitl"),
    ("PUT", "/api/runs/{run_id}/hitl/responses"),
    ("POST", "/api/runs/{run_id}/hitl/submit"),
    ("POST", "/api/runs/{run_id}/hitl/approve"),
    ("POST", "/api/runs/{run_id}/resume"),
    ("GET", "/api/runs/{run_id}/pr/status"),
    ("POST", "/api/runs/{run_id}/pr/shepherd"),
    ("POST", "/api/runs/{run_id}/pr/approve-merge"),
    ("POST", "/api/runs/{run_id}/pause"),
    ("POST", "/api/runs/{run_id}/inject"),
    ("GET", "/api/runs/{run_id}/injects"),
    ("POST", "/api/runs/{run_id}/reconcile-graph"),
    ("GET", "/api/runs/{run_id}/waves"),
    ("GET", "/api/waves/{run_id}/{node_id:path}"),
    ("GET", "/api/runs/{run_id}/waves/{node_id:path}/log"),
    ("GET", "/api/runs/{run_id}/waves/{node_id:path}/worktree"),
    ("GET", "/api/runs/{run_id}/events"),
    ("GET", "/api/runs/{run_id}/events/stream"),
    ("GET", "/api/config"),
    ("PUT", "/api/config"),
    ("GET", "/api/backends"),
)

EXPECTED_UI_ROUTES: tuple[tuple[str, str], ...] = (
    ("GET", "/"),
    ("POST", "/launch"),
    ("GET", "/agents"),
    ("GET", "/agents/new"),
    ("POST", "/agents/new"),
    ("GET", "/agents/{profile_id}/edit"),
    ("POST", "/agents/{profile_id}/edit"),
    ("GET", "/settings"),
    ("POST", "/settings"),
    ("GET", "/runs/{run_id}"),
    ("POST", "/runs/{run_id}/pr/approve-merge"),
    ("POST", "/runs/{run_id}/inject"),
    ("GET", "/runs/{run_id}/timeline"),
    ("GET", "/runs/{run_id}/waves/{node_id:path}/log"),
    ("GET", "/runs/{run_id}/waves/{node_id:path}/log/append"),
    ("GET", "/runs/{run_id}/waves/{node_id:path}/log/full"),
    ("GET", "/runs/{run_id}/waves-table"),
    ("GET", "/runs/{run_id}/waves/{node_id:path}/worktree"),
    ("GET", "/runs/{run_id}/waves/{node_id:path}/tasks"),
    ("GET", "/runs/{run_id}/batch-timeline"),
    ("GET", "/runs/{run_id}/report"),
    ("GET", "/runs/{run_id}/orchestrator"),
)


def _cmd_name(cmd: typer.models.CommandInfo) -> str | None:
    if cmd.name:
        return cmd.name
    if cmd.callback:
        return cmd.callback.__name__.lstrip("_")
    return None


def _cli_command_inventory(app: typer.Typer) -> list[str]:
    """Return leaf command names in Typer registration order (includes hidden run-*)."""
    ordered: list[str] = []
    for cmd in app.registered_commands:
        name = _cmd_name(cmd)
        if name:
            ordered.append(name)

    sub = typer.Typer()
    register_run_commands(sub)
    hidden = [c.name for c in sub.registered_commands if c.hidden and c.name]
    if "run" in ordered:
        insert_at = ordered.index("run") + 1
        for hidden_name in reversed(hidden):
            if hidden_name not in ordered:
                ordered.insert(insert_at, hidden_name)

    def walk_group(group_app: typer.Typer, prefix: str) -> None:
        for cmd in group_app.registered_commands:
            name = _cmd_name(cmd)
            if name:
                ordered.append(f"{prefix} {name}")
        for grp in group_app.registered_groups:
            walk_group(grp.typer_instance, f"{prefix} {grp.name}")

    for grp in app.registered_groups:
        walk_group(grp.typer_instance, grp.name)

    return ordered


def _collect_imported_ledger_names(*, roots: Iterable[Path]) -> set[str]:
    names: set[str] = set()
    for root in roots:
        for path in root.rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "tripll.ledger":
                    for alias in node.names:
                        if alias.name != "*":
                            names.add(alias.name)
    return names


def _collect_api_routes(app: Any) -> list[tuple[str, str, bool]]:
    from fastapi.routing import APIRoute

    routes: list[tuple[str, str, bool]] = []

    def walk(route_list: list[Any], prefix: str = "") -> None:
        for route in route_list:
            if isinstance(route, APIRoute):
                for method in sorted(route.methods or []):
                    routes.append(
                        (method, prefix + route.path, getattr(route, "include_in_schema", True))
                    )

    walk(app.routes)
    routes.sort(key=lambda item: (item[1], item[0]))
    return routes


def _assert_resolves(module: Any, name: str) -> None:
    assert hasattr(module, name), f"{module.__name__}.{name} missing from façade"
    assert getattr(module, name) is not None


@pytest.mark.parametrize(
    "name",
    engine_mod.__all__,
)
def test_engine_public_surface_resolves(name: str) -> None:
    """Every ``engine.__all__`` entry resolves from ``tripll.engine``."""
    _assert_resolves(engine_mod, name)


def test_engine_scheduling_identity_reexports() -> None:
    """Extracted scheduling symbols stay identical objects on the engine façade."""
    assert ready_nodes is scheduling_ready_nodes
    assert can_run_concurrently is scheduling_can_run_concurrently
    assert select_concurrent_set is scheduling_select_concurrent_set
    assert human_gate_node_ids is scheduling_human_gate_node_ids
    assert nodes_for_batch is scheduling_nodes_for_batch
    assert orchestrator_serial_nodes is scheduling_orchestrator_serial_nodes


@pytest.mark.parametrize(
    "name",
    sorted(_collect_imported_ledger_names(roots=[_REPO_ROOT / "src", _REPO_ROOT / "tests"])),
)
def test_ledger_imported_names_resolve(name: str) -> None:
    """Every name imported from ``tripll.ledger`` resolves on the ledger façade."""
    _assert_resolves(ledger_mod, name)


def test_cli_run_identity_reexports() -> None:
    """CLI run seam stays aligned with ``cli._run``."""
    assert register_run_commands is cli_run.register_run_commands
    assert rewrite_run_inject_argv is cli_run.rewrite_run_inject_argv
    assert cli_pkg._rewrite_run_inject_argv is cli_run.rewrite_run_inject_argv


def test_api_app_create_app_resolves() -> None:
    """``create_app`` remains the documented public export."""
    _assert_resolves(api_app, "create_app")
    assert callable(create_app)


@pytest.mark.parametrize(
    ("module", "name"),
    [
        (engine_mod, "_resolve_grep_brief"),
        (engine_mod, "_MAX_NO_PROGRESS_DISPATCHES"),
        (engine_mod, "__doc__"),
        (cli_pkg, "_run_integration"),
        (cli_pkg, "_orchestrator_watch_lines"),
        (cli_pkg, "_rewrite_run_inject_argv"),
        (api_app, "_resolve_runs_root"),
        (api_app, "_read_config"),
        (api_app, "_slug_profile_id"),
        (api_app, "_tripll_argv"),
    ],
)
def test_private_name_table_resolves(module: Any, name: str) -> None:
    """Private names reached from tests or production must survive façade extractions."""
    _assert_resolves(module, name)


@pytest.mark.xfail(reason="green after W3: ledger.__all__ completeness", strict=False)
def test_ledger_all_contains_every_imported_name() -> None:
    """``ledger.__all__`` must list every externally imported name (W3 façade contract)."""
    imported = _collect_imported_ledger_names(roots=[_REPO_ROOT / "src", _REPO_ROOT / "tests"])
    all_names = getattr(ledger_mod, "__all__", None)
    assert isinstance(all_names, (list, tuple)), "tripll.ledger must define __all__"
    missing = sorted(imported - set(all_names))
    assert missing == [], f"ledger.__all__ missing: {missing}"


def test_cli_command_inventory_snapshot() -> None:
    """Typer command inventory matches baseline registration order (tier 3)."""
    inventory = _cli_command_inventory(cli_app)
    assert inventory == list(EXPECTED_CLI_COMMANDS)
    assert "run-inject" in inventory
    assert "run-reconcile-graph" in inventory
    group_names = [grp.name for grp in cli_app.registered_groups]
    assert group_names == list(EXPECTED_CLI_GROUPS)
    assert len(group_names) == 12


def test_cli_help_lists_hidden_run_commands() -> None:
    """Hidden run-inject / run-reconcile-graph remain registered (W6 guard)."""
    result = _CLI_RUNNER.invoke(cli_app, ["--help"])
    assert result.exit_code == 0
    assert "run-inject" not in result.output  # hidden from help text
    hidden_app = typer.Typer()
    register_run_commands(hidden_app)
    hidden_names = {c.name for c in hidden_app.registered_commands if c.hidden}
    assert hidden_names == {"run-inject", "run-reconcile-graph"}


def test_create_app_route_table_snapshot() -> None:
    """JSON + dashboard route inventories lock W7/W8 surface (tier 3)."""
    app = create_app()
    json_routes = sorted(
        (method, path)
        for method, path, _include in _collect_api_routes(app)
        if path.startswith("/api") or path == "/health"
    )
    assert json_routes == sorted(EXPECTED_JSON_ROUTES)

    ui_router = make_ui_router()
    assert ui_router.include_in_schema is False
    ui_routes = sorted((method, path) for method, path, _inc in _collect_api_routes(ui_router))
    assert ui_routes == sorted(EXPECTED_UI_ROUTES)

    assert "run-inject" in EXPECTED_CLI_COMMANDS or "run-reconcile-graph" in EXPECTED_CLI_COMMANDS
