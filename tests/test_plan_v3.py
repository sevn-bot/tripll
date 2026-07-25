"""Plan format v3 — parse/emit, compat v1/v2 (W1.6)."""

from __future__ import annotations

from pathlib import Path

from tests.conftest import require_module

_FIXTURES = Path(__file__).parent / "fixtures" / "plans"


def test_v3_round_trip() -> None:
    parse_plan_v3 = require_module("tripll.plan.format_v3", attr="parse_plan_v3")
    emit_plan_v3 = require_module("tripll.plan.format_v3", attr="emit_plan_v3")
    raw = (_FIXTURES / "v3_full.md").read_text()
    plan = parse_plan_v3(raw)
    out = emit_plan_v3(plan)
    assert "waveorch_format = 3" in out
    assert plan["target_repo"] == "sevn-bot/tripll"


def test_v1_fixture_reads_with_warning() -> None:
    read_legacy_plan = require_module("tripll.plan.compat_v1_v2", attr="read_legacy_plan")
    plan, warnings = read_legacy_plan(_FIXTURES / "v1_minimal.md")
    assert warnings
    assert plan.get("waveorch_format") == 3


def test_v2_fixture_reads_with_warning_once() -> None:
    read_legacy_plan = require_module("tripll.plan.compat_v1_v2", attr="read_legacy_plan")
    path = _FIXTURES / "v2_minimal.md"
    _plan1, w1 = read_legacy_plan(path)
    _plan2, w2 = read_legacy_plan(path)
    assert w1
    assert w2 == []


def test_target_repo_deadline_budget_targets_outcome_parse() -> None:
    parse_plan_v3 = require_module("tripll.plan.format_v3", attr="parse_plan_v3")
    plan = parse_plan_v3((_FIXTURES / "v3_full.md").read_text())
    assert plan["target_repo"] == "sevn-bot/tripll"
    assert plan["pipeline"]["deadline"] == "6h"
    assert plan["pipeline"]["budget_usd"] == 25.0
    wave = plan["waves"][0]
    assert wave["targets"] == ["src/tripll/graphstore/sqlite_store.py"]
    assert wave["outcome"]["required"]
