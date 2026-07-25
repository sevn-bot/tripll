"""Graph-packed brief — seeds, hops, handoff contract (W1.13)."""

from __future__ import annotations

from tripll.serve.brief_packer import pack_brief
from tripll.serve.handoff import build_handoff, validate_handoff

_HANDOFF_FIELDS = [
    "objective",
    "scope_accepted",
    "decisions_made",
    "files_changed",
    "external_state_changed",
    "tests_run_and_results",
    "known_failures",
    "git_workspace_state",
    "next_safe_action",
    "approval_still_required",
]


def test_seeds_from_targets() -> None:
    brief = pack_brief(
        wave={"id": "W2", "targets": ["src/tripll/graphstore/sqlite_store.py"]},
        graph_store=":memory:",
        at_sha="abc",
    )
    assert brief["seeds"]
    assert any("graphstore" in s for s in brief["seeds"])


def test_two_hop_cap_enforced() -> None:
    brief = pack_brief(
        wave={"id": "W2", "targets": ["src/a.py"]},
        graph_store=":memory:",
        at_sha="abc",
        max_hops=2,
    )
    assert brief["max_hops"] <= 2


def test_findings_contribute_paths_not_neighbourhoods() -> None:
    brief = pack_brief(
        wave={"id": "W2", "targets": ["src/a.py"]},
        graph_store=":memory:",
        open_findings=[{"finding_id": "f1"}],
        at_sha="abc",
    )
    assert brief["finding_paths"]
    assert not brief.get("finding_neighbourhoods")


def test_triple_tables_with_provenance() -> None:
    brief = pack_brief(
        wave={"id": "W2", "targets": ["src/a.py"]},
        graph_store=":memory:",
        at_sha="abc",
    )
    table = brief["triple_table"]
    assert "|" in table or "predicate" in table
    assert "file:" in table or "evidence" in table


def test_token_cap_spills_to_file(tmp_path) -> None:  # type: ignore[no-untyped-def]
    brief = pack_brief(
        wave={"id": "W2", "targets": ["src/a.py"]},
        graph_store=":memory:",
        at_sha="abc",
        run_dir=tmp_path,
        per_field_token_cap=10,
    )
    assert brief.get("spill_files") or brief.get("spilled_fields")


def test_handoff_block_has_ten_fields() -> None:
    handoff = build_handoff(
        objective="finish W2",
        scope_accepted=["src/tripll/graphstore/"],
        decisions_made=["SQLite of record"],
        files_changed=[],
        external_state_changed=[],
        tests_run_and_results={"make test": "xfail"},
        known_failures=[],
        git_workspace_state={"clean": True},
        next_safe_action="implement GraphStore",
        approval_still_required=[],
    )
    for field in _HANDOFF_FIELDS:
        assert field in handoff


def test_fresh_session_identifies_next_action_from_handoff_only() -> None:
    handoff = {
        "objective": "W2 GraphStore",
        "next_safe_action": "implement src/tripll/graphstore/sqlite_store.py",
    }
    assert validate_handoff(handoff)["action_identified"] is True
