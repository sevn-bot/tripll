"""Finding -> proposed Rule promotion and operator lifecycle (W3.3-W3.4, R27).

Exports:
    promote_rule — operator-only ``proposed`` -> ``active``.
    propose_rule_from_finding — resolved Finding -> ``proposed`` Rule with ``finding://`` origin.
    retire_rule — operator-only ``active`` -> ``retired``.
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path  # noqa: TC003 — runtime repo slug resolution
from typing import TYPE_CHECKING, Any

from tripll.rules.model import Rule
from tripll.rules.store import RuleStore  # noqa: TC001 — runtime store writes

if TYPE_CHECKING:
    from tripll.graphstore import GraphStore

__all__ = [
    "promote_rule",
    "propose_rule_from_finding",
    "retire_rule",
]

_RESOLVED_STATES = frozenset({"resolved", "fixed", "accepted"})
_ACTIVE_STATE = "active"
_RETIRED_STATE = "retired"
_PROPOSED_STATE = "proposed"


def _slugify_rule_id(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:64] or "promoted-rule"


def _suggested_test_name(rule_id: str) -> str:
    slug = rule_id.replace("-", "_")
    return f"tests/test_rules.py::test_{slug}"


def _default_scope(finding: dict[str, Any]) -> list[str]:
    file_ = finding.get("file")
    if isinstance(file_, str) and file_.startswith("src/"):
        return ["src/**"]
    return ["**"]


def _rule_body_from_finding(finding: dict[str, Any], *, rule_id: str) -> str:
    message = str(finding.get("message_raw") or finding.get("rule_id") or "defect")
    test_name = _suggested_test_name(rule_id)
    file_ = finding.get("file")
    line_range = finding.get("line_range")
    evidence = ""
    if file_ and line_range and isinstance(line_range, list) and line_range:
        evidence = f"`{file_}:{line_range[0]}`"
    elif file_:
        evidence = f"`{file_}`"

    if "logging" in message.lower():
        body = (
            "Use loguru; never stdlib `logging`.\n\n"
            f"**Why:** Promoted from finding — {message.strip()}.\n"
        )
    else:
        body = f"{message.strip()}\n\n**Why:** Promoted from a resolved finding.\n"

    if evidence:
        body += f"**Evidence:** {evidence}.\n"
    body += f"**Test:** `{test_name}`\n"
    return body


def _finding_to_proposed_rule(finding: dict[str, Any]) -> Rule:
    run_id = str(finding.get("run_id") or "local")
    finding_id = str(finding.get("finding_id") or "unknown")
    origin = f"finding://{run_id}#{finding_id}"
    message = str(finding.get("message_raw") or finding.get("rule_id") or "defect")
    rule_id = _slugify_rule_id(message)
    if "logging" in message.lower():
        rule_id = "no-stdlib-logging"
    return Rule(
        rule_id=rule_id,
        state=_PROPOSED_STATE,
        origin=origin,
        scope=_default_scope(finding),
        body=_rule_body_from_finding(finding, rule_id=rule_id),
    )


def _repo_slug(repo_root: Path) -> str:
    return repo_root.name or "local"


def propose_rule_from_finding(
    finding: dict[str, Any],
    *,
    store: RuleStore,
    graph_store: GraphStore | str | None = None,
    repo: str | None = None,
) -> Rule:
    """Propose a durable rule from a resolved finding (RULE-02).

    Writes state ``proposed`` only — activation requires :func:`promote_rule` (R27).

    Args:
        finding (dict[str, Any]): Finding dict (``state`` must be resolved/fixed/accepted).
        store (RuleStore): Rule filesystem store.
        graph_store (GraphStore | str | None): Optional graph for Rule node upsert.
        repo (str | None): Repo slug for graph natural key; defaults to repo root name.

    Returns:
        Rule: Newly written proposed rule.

    Raises:
        ValueError: When the finding is not in a resolved state.
    """
    state = str(finding.get("state") or "")
    if state not in _RESOLVED_STATES:
        msg = f"finding state {state!r} is not resolved — only {_RESOLVED_STATES} may propose"
        raise ValueError(msg)

    rule = _finding_to_proposed_rule(finding)
    store.write_rule(rule, force=True)
    if graph_store is not None:
        from tripll.graphstore.task_sync import sync_rule_to_store

        sync_rule_to_store(
            rule,
            finding=finding,
            store=graph_store,
            repo=repo or _repo_slug(store.repo_root),
        )
    return rule


def promote_rule(
    rule_id: str,
    *,
    store: RuleStore,
    graph_store: GraphStore | str | None = None,
    repo: str | None = None,
) -> Rule:
    """Operator-only promotion from ``proposed`` to ``active`` (R27).

    Args:
        rule_id (str): Rule slug to activate.
        store (RuleStore): Rule filesystem store.
        graph_store (GraphStore | str | None): Optional graph store for node sync.
        repo (str | None): Repo slug for graph natural key.

    Returns:
        Rule: Updated active rule.

    Raises:
        FileNotFoundError: When the rule file is missing.
        ValueError: When the rule is not in ``proposed`` state.
    """
    existing = store.read_rule(rule_id)
    if existing is None:
        msg = f"rule {rule_id!r} not found under {store.rules_path}"
        raise FileNotFoundError(msg)
    if existing.state != _PROPOSED_STATE:
        msg = f"rule {rule_id!r} is {existing.state!r}; only proposed rules may be promoted"
        raise ValueError(msg)

    active = replace(existing, state=_ACTIVE_STATE)
    store.write_rule(active, force=True, via_operator=True)
    if graph_store is not None:
        from tripll.graphstore.task_sync import sync_rule_to_store

        sync_rule_to_store(
            active,
            store=graph_store,
            repo=repo or _repo_slug(store.repo_root),
        )
    return active


def retire_rule(
    rule_id: str,
    *,
    store: RuleStore,
    graph_store: GraphStore | str | None = None,
    repo: str | None = None,
) -> Rule:
    """Operator-only retirement to ``retired`` (superseded or wrong).

    Args:
        rule_id (str): Rule slug to retire.
        store (RuleStore): Rule filesystem store.
        graph_store (GraphStore | str | None): Optional graph store for node sync.
        repo (str | None): Repo slug for graph natural key.

    Returns:
        Rule: Updated retired rule.

    Raises:
        FileNotFoundError: When the rule file is missing.
    """
    existing = store.read_rule(rule_id)
    if existing is None:
        msg = f"rule {rule_id!r} not found under {store.rules_path}"
        raise FileNotFoundError(msg)

    retired = replace(existing, state=_RETIRED_STATE)
    store.write_rule(retired, force=True, via_operator=True)
    if graph_store is not None:
        from tripll.graphstore.task_sync import sync_rule_to_store

        sync_rule_to_store(
            retired,
            store=graph_store,
            repo=repo or _repo_slug(store.repo_root),
        )
    return retired
