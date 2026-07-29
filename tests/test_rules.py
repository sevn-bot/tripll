"""Rule model, packing, and compounding e2e (W1.1, W1.3, W1.8)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.rules._helpers import SAMPLE_RULE_FRONTMATTER, require_attr

pytest_plugins = ["tests.rules._helpers"]
pytestmark = pytest.mark.tier1


@pytest.mark.xfail(reason="green after W2: rule model and origin validator", strict=False)
def test_rule_three_states_are_proposed_active_retired() -> None:
    """Only the three lifecycle states are valid (R27)."""
    rule_states = require_attr("tripll.rules.model", "RULE_STATES")
    assert rule_states == frozenset({"proposed", "active", "retired"})


@pytest.mark.xfail(reason="green after W2: frontmatter round trip", strict=False)
def test_rule_frontmatter_round_trip_preserves_fields(tmp_path: Path) -> None:
    """Parse → render → parse preserves rule_id, state, origin, scope."""
    parse_rule_markdown = require_attr("tripll.rules.model", "parse_rule_markdown")
    render_rule_markdown = require_attr("tripll.rules.model", "render_rule_markdown")
    path = tmp_path / "no-stdlib-logging.md"
    path.write_text(SAMPLE_RULE_FRONTMATTER, encoding="utf-8")
    first = parse_rule_markdown(path.read_text(encoding="utf-8"))
    second = parse_rule_markdown(render_rule_markdown(first))
    assert second.rule_id == first.rule_id == "no-stdlib-logging"
    assert second.state == first.state == "active"
    assert second.origin == first.origin == "codebase://src/widget.py:1"
    assert second.scope == first.scope == ["src/**"]


@pytest.mark.xfail(reason="green after W2: origin validator accepts resolving refs", strict=False)
def test_origin_codebase_resolves_when_file_line_exists(
    rules_foreign_repo: Path,
) -> None:
    """codebase:// origins must resolve to a real file:line (R26)."""
    validate_origin = require_attr("tripll.rules.model", "validate_origin")
    validate_origin("codebase://src/widget.py:1", repo_root=rules_foreign_repo)


@pytest.mark.xfail(reason="green after W2: finding origin format", strict=False)
def test_origin_finding_format_accepted() -> None:
    """Promoted rules may cite finding://<run>#<id> (W3 contract)."""
    validate_origin = require_attr("tripll.rules.model", "validate_origin")
    validate_origin("finding://l1-remediation#F-014", repo_root=Path("."))


@pytest.mark.xfail(reason="green after W2: origin validator rejects missing origin", strict=False)
def test_origin_missing_rejected() -> None:
    """A rule without origin is rejected — it is an opinion, not a constraint."""
    parse_rule_markdown = require_attr("tripll.rules.model", "parse_rule_markdown")
    validate_rule = require_attr("tripll.rules.model", "validate_rule")
    rule = parse_rule_markdown(
        "---\nrule_id: orphan\nstate: proposed\nscope: []\n---\n\nNo origin.\n"
    )
    with pytest.raises(Exception, match="origin"):
        validate_rule(rule, repo_root=Path("."))


@pytest.mark.xfail(
    reason="green after W2: unresolving origin names offending ref",
    strict=False,
)
def test_origin_unresolving_file_line_rejected_names_ref(
    rules_foreign_repo: Path,
) -> None:
    """Validator error must name the offending origin ref (W1.1)."""
    validate_origin = require_attr("tripll.rules.model", "validate_origin")
    bad_ref = "codebase://src/missing.py:99"
    origin_error = require_attr("tripll.rules.model", "OriginValidationError")
    with pytest.raises(origin_error, match=r"missing\.py:99"):
        validate_origin(bad_ref, repo_root=rules_foreign_repo)


@pytest.mark.xfail(reason="green after W2: scope intersection packing", strict=False)
def test_pack_scope_intersection_selects_context_modules() -> None:
    """Only context modules whose scope intersects wave targets are packed (R31)."""
    pack_rules_for_brief = require_attr("tripll.rules.pack", "pack_rules_for_brief")
    context_module = require_attr("tripll.rules.pack", "ContextModule")
    rule = require_attr("tripll.rules.model", "Rule")
    active = rule(
        rule_id="r1",
        state="active",
        origin="codebase://src/a.py:1",
        scope=["src/**"],
        body="Always log with loguru.",
    )
    auth_ctx = context_module(
        topic="auth",
        scope=["src/tripll/auth/**"],
        body="JWT is forward; session cookies are legacy.",
    )
    cli_ctx = context_module(
        topic="cli",
        scope=["src/tripll/cli/**"],
        body="Typer app lives in cli/__init__.py.",
    )
    packed = pack_rules_for_brief(
        rules=[active],
        context_modules=[auth_ctx, cli_ctx],
        wave_targets=["src/tripll/cli/__init__.py"],
        budget_tokens=1200,
    )
    assert "Typer app" in packed
    assert "JWT is forward" not in packed


@pytest.mark.xfail(reason="green after W2: pack_budget_tokens ceiling", strict=False)
def test_pack_never_exceeds_budget_tokens() -> None:
    """Rules+context pack must stay within pack_budget_tokens (R31)."""
    pack_rules_for_brief = require_attr("tripll.rules.pack", "pack_rules_for_brief")
    estimate_tokens = require_attr("tripll.rules.pack", "estimate_tokens")
    context_module = require_attr("tripll.rules.pack", "ContextModule")
    rule = require_attr("tripll.rules.model", "Rule")
    budget = 120
    rules = [
        rule(
            rule_id=f"r{i}",
            state="active",
            origin=f"codebase://src/a.py:{i}",
            scope=["src/**"],
            body=f"Rule body {i} " * 20,
        )
        for i in range(3)
    ]
    modules = [
        context_module(
            topic=f"m{i}",
            scope=["src/**"],
            body=f"Context filler {i} " * 50,
        )
        for i in range(5)
    ]
    packed = pack_rules_for_brief(
        rules=rules,
        context_modules=modules,
        wave_targets=["src/**"],
        budget_tokens=budget,
    )
    assert estimate_tokens(packed) <= budget


@pytest.mark.xfail(reason="green after W2: empty rule set yields empty pack", strict=False)
def test_empty_rule_set_yields_empty_pack_not_crash() -> None:
    """An empty active rule set yields an empty pack string, not an exception."""
    pack_rules_for_brief = require_attr("tripll.rules.pack", "pack_rules_for_brief")
    packed = pack_rules_for_brief(
        rules=[],
        context_modules=[],
        wave_targets=["src/tripll/rules/model.py"],
        budget_tokens=1200,
    )
    assert packed == ""


@pytest.mark.tier3
@pytest.mark.xfail(
    reason="green after W3: derive → propose → promote → pack e2e",
    strict=False,
)
def test_e2e_derive_propose_promote_pack_reaches_brief(
    rules_foreign_repo: Path,
    tmp_path: Path,
) -> None:
    """Tier-3 smoke: full compounding loop lands an active rule in a brief."""
    derive_rules = require_attr("tripll.rules.derive", "derive_rules")
    propose_rule_from_finding = require_attr("tripll.rules.promote", "propose_rule_from_finding")
    promote_rule = require_attr("tripll.rules.promote", "promote_rule")
    pack_rules_for_brief = require_attr("tripll.rules.pack", "pack_rules_for_brief")
    rule_store_cls = require_attr("tripll.rules.store", "RuleStore")

    rules_dir = rules_foreign_repo / ".tripll" / "rules"
    derive_rules(rules_foreign_repo, rules_dir=rules_dir)
    assert list(rules_dir.glob("*.md"))

    finding = {
        "finding_id": "F-001",
        "run_id": "run-a",
        "state": "resolved",
        "file": "src/widget.py",
        "line_range": [1, 1],
        "message_raw": "stdlib logging detected",
    }
    store = rule_store_cls(rules_foreign_repo)
    proposed = propose_rule_from_finding(finding, store=store)
    assert proposed.state == "proposed"
    assert proposed.origin == "finding://run-a#F-001"

    active = promote_rule(proposed.rule_id, store=store)
    assert active.state == "active"

    packed = pack_rules_for_brief(
        rules=store.list_active(),
        context_modules=[],
        wave_targets=["src/widget.py"],
        budget_tokens=1200,
    )
    assert "loguru" in packed.lower() or "logging" in packed.lower()

    brief_path = tmp_path / "brief.md"
    brief_path.write_text(f"# Dispatch\n\n{packed}\n", encoding="utf-8")
    assert "stdlib" in brief_path.read_text(encoding="utf-8").lower()
