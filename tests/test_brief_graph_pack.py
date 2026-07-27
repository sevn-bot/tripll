"""Graph-packed brief enrichment — insufficiency fallback and grep-brief regression."""

from __future__ import annotations

from pathlib import Path

from tripll.brief import (
    AGENT_DIRECTIVES,
    GRAPH_PACKED_DIRECTIVE,
    GREP_EXPLORATION_DIRECTIVE,
    PACK_INSUFFICIENCY_MARKER,
    PACKED_INSUFFICIENCY_DIRECTIVE,
    enrich_brief_with_graph_pack,
    render_dispatch_prompt,
    render_json_brief,
)
from tripll.engine import _resolve_grep_brief
from tripll.extract._common import make_node, provenance
from tripll.graph import WaveNode
from tripll.graphstore import SqliteGraphStore

_PROV = provenance(source="test", evidence="tests/test_brief_graph_pack.py", extractor="test")


def _base_brief(*, wave_id: str = "W1", owned_paths: list[str] | None = None) -> dict[str, object]:
    node = WaveNode(
        f"l:{wave_id}",
        "l",
        "plan.md",
        wave_id,
        "lane",
        owned_paths=owned_paths or ["src/tripll/brief.py"],
    )
    return render_json_brief(
        node,
        run_id="run-1",
        branch="wave/run-1/l-w1",
        worktree_path="/wt",
    )


def _seed_module(store: SqliteGraphStore, path: str) -> None:
    store.upsert_nodes(
        [
            make_node(
                layer="code",
                kind="Module",
                natural_key=path,
                repo="tripll",
                props={"path": path},
                **(_PROV | {"extractor": "test"}),
            )
        ]
    )


def test_populated_graph_pack_non_empty(tmp_path: Path) -> None:
    db = tmp_path / "graph.db"
    store = SqliteGraphStore(str(db))
    _seed_module(store, "src/tripll/brief.py")
    store.close()

    brief = _base_brief()
    enriched = enrich_brief_with_graph_pack(
        brief,
        wave_targets=["src/tripll/brief.py"],
        graph_store=str(db),
        at_sha="abc",
    )

    graph_pack = enriched.get("graph_pack")
    assert isinstance(graph_pack, dict)
    assert graph_pack.get("subgraph_nodes", 0) >= 1
    assert enriched.get("grep_brief") is False
    assert PACK_INSUFFICIENCY_MARKER not in enriched
    assert GRAPH_PACKED_DIRECTIVE in enriched["agent_directives"]
    assert PACKED_INSUFFICIENCY_DIRECTIVE not in enriched["agent_directives"]


def test_empty_graph_signals_insufficiency(tmp_path: Path) -> None:
    db = tmp_path / "graph.db"
    SqliteGraphStore(str(db)).close()

    brief = _base_brief()
    enriched = enrich_brief_with_graph_pack(
        brief,
        wave_targets=["src/tripll/brief.py"],
        graph_store=str(db),
        at_sha="abc",
    )

    assert enriched.get(PACK_INSUFFICIENCY_MARKER) is True
    assert enriched.get("grep_brief") is False
    directives = enriched["agent_directives"]
    assert GRAPH_PACKED_DIRECTIVE in directives
    assert PACKED_INSUFFICIENCY_DIRECTIVE in directives
    prompt = render_dispatch_prompt(enriched)
    assert "insufficient" in prompt.lower()
    assert "workspace_scope" in prompt


def test_grep_brief_forces_legacy_directive() -> None:
    brief = _base_brief()
    enriched = enrich_brief_with_graph_pack(
        brief,
        wave_targets=["src/tripll/brief.py"],
        graph_store=":memory:",
        at_sha="abc",
        grep_brief=True,
    )

    assert enriched.get("grep_brief") is True
    assert "graph_pack" not in enriched
    assert GREP_EXPLORATION_DIRECTIVE in enriched["agent_directives"]
    assert GRAPH_PACKED_DIRECTIVE not in enriched["agent_directives"]


def test_resolve_grep_brief_without_kg_extra(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("tripll.plan.code_graph.kg_extra_available", lambda: False)
    assert _resolve_grep_brief(None) is True
    assert _resolve_grep_brief(True) is True
    assert _resolve_grep_brief(False) is False


def test_resolve_grep_brief_defaults_graph_when_kg_installed(
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    monkeypatch.setattr("tripll.plan.code_graph.kg_extra_available", lambda: True)
    assert _resolve_grep_brief(None) is False


def test_default_agent_directives_keep_graph_packed_directive() -> None:
    assert GRAPH_PACKED_DIRECTIVE in AGENT_DIRECTIVES
