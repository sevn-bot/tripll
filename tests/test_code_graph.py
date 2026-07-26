"""Code graph activation — stop rule, routing hints, degradation (P2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import require_module
from tripll.extract._common import make_edge, make_node, provenance
from tripll.graphstore import SqliteGraphStore

REPO_ROOT = Path(__file__).resolve().parents[1]
_PROV = provenance(source="test", evidence="tests/test_code_graph.py", extractor="test")


@pytest.fixture
def kg_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tripll.plan.code_graph.kg_extra_available", lambda: True)


def _seed_calls_adjacent_modules(store: SqliteGraphStore, *, repo: str = "test") -> None:
    """Two modules whose symbols are joined by a one-hop CALLS edge."""
    mod_a = make_node(
        layer="code",
        kind="Module",
        natural_key=f"{repo}#src/a.py",
        repo=repo,
        props={"path": "src/a.py"},
        **(_PROV | {"extractor": "test"}),
    )
    mod_b = make_node(
        layer="code",
        kind="Module",
        natural_key=f"{repo}#src/b.py",
        repo=repo,
        props={"path": "src/b.py"},
        **(_PROV | {"extractor": "test"}),
    )
    sym_a = make_node(
        layer="code",
        kind="Symbol",
        natural_key=f"{repo}#src/a.py::caller",
        repo=repo,
        props={"qualname": "caller"},
        **(_PROV | {"extractor": "test"}),
    )
    sym_b = make_node(
        layer="code",
        kind="Symbol",
        natural_key=f"{repo}#src/b.py::callee",
        repo=repo,
        props={"qualname": "callee"},
        **(_PROV | {"extractor": "test"}),
    )
    store.upsert_nodes([mod_a, mod_b, sym_a, sym_b])
    store.upsert_edges(
        [
            make_edge(
                predicate="DECLARES",
                src=mod_a["node_id"],
                dst=sym_a["node_id"],
                **(_PROV | {"extractor": "test"}),
            ),
            make_edge(
                predicate="DECLARES",
                src=mod_b["node_id"],
                dst=sym_b["node_id"],
                **(_PROV | {"extractor": "test"}),
            ),
            make_edge(
                predicate="CALLS",
                src=sym_a["node_id"],
                dst=sym_b["node_id"],
                **(_PROV | {"extractor": "test"}),
            ),
        ]
    )


def test_kg_extra_available_is_bool() -> None:
    kg_extra_available = require_module("tripll.plan.code_graph", attr="kg_extra_available")
    assert isinstance(kg_extra_available(), bool)


def test_analyze_parallel_calls_refuses_adjacent_modules(tmp_path: Path, kg_enabled: None) -> None:
    analyze_parallel_calls = require_module(
        "tripll.plan.code_graph",
        attr="analyze_parallel_calls",
    )
    db = tmp_path / "graph.db"
    store = SqliteGraphStore(str(db))
    _seed_calls_adjacent_modules(store)
    store.close()
    payload = analyze_parallel_calls(
        [
            {"id": "W1", "targets": ["src/a.py"]},
            {"id": "W2", "targets": ["src/b.py"]},
        ],
        graph_store=str(db),
        repo="test",
    )
    assert payload is not None
    assert payload["parallel"] is True
    assert payload["calls_path_len"] <= 1


def test_calls_adjacent_parallel_refused(tmp_path: Path, kg_enabled: None) -> None:
    compile_plan = require_module("tripll.plan.shape_checks", attr="compile_plan")
    db = tmp_path / "graph.db"
    store = SqliteGraphStore(str(db))
    _seed_calls_adjacent_modules(store)
    store.close()
    with pytest.raises(ValueError, match=r"sequential|stop|CALLS"):
        compile_plan(
            {
                "waves": [
                    {"id": "W1", "targets": ["src/a.py"]},
                    {"id": "W2", "targets": ["src/b.py"]},
                ],
            },
            graph_db=db,
            repo="test",
        )


def test_independent_parallel_waves_compile_with_code_graph(
    tmp_path: Path, kg_enabled: None
) -> None:
    compile_plan = require_module("tripll.plan.shape_checks", attr="compile_plan")
    db = tmp_path / "graph.db"
    SqliteGraphStore(str(db)).close()
    compiled = compile_plan(
        {
            "waves": [
                {"id": "W1", "targets": ["src/a.py", "src/b.py"]},
                {"id": "W2", "targets": ["src/c.py", "src/d.py"]},
            ],
        },
        graph_db=db,
        repo="test",
    )
    assert len(compiled["waves"]) == 2


def test_compile_plan_without_graph_db_uses_per_wave_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compile_plan = require_module("tripll.plan.shape_checks", attr="compile_plan")
    monkeypatch.setattr("tripll.plan.code_graph.kg_extra_available", lambda: False)
    with pytest.raises(ValueError, match=r"cross-cutting|refactor|sequential"):
        compile_plan(
            {
                "waves": [
                    {
                        "id": "W1",
                        "targets": [
                            "src/a.py",
                            "src/b.py",
                            "src/c.py",
                            "src/d.py",
                            "src/e.py",
                            "src/f.py",
                        ],
                    },
                ],
            },
        )


def test_routing_hints_are_advisory_only(tmp_path: Path, kg_enabled: None) -> None:
    routing_hints_for_wave = require_module(
        "tripll.plan.code_graph",
        attr="routing_hints_for_wave",
    )
    from tripll.adapters.pools import ProviderConfig

    db = tmp_path / "graph.db"
    store = SqliteGraphStore(str(db))
    _seed_calls_adjacent_modules(store)
    store.close()
    hints = routing_hints_for_wave(
        targets=["src/a.py", "src/b.py"],
        graph_store=str(db),
        provider="cursor_local",
        provider_config=ProviderConfig(max_parallel=5, default_model="auto"),
        repo="test",
    )
    assert hints["module_count"] == 2
    assert hints["advisory"] is True
    assert hints["provider"] == "cursor_local"
    assert hints["provider_max_parallel"] == 5
    assert "selected_model" not in hints


def test_refresh_code_graph_skips_without_kg(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    refresh_code_graph = require_module("tripll.plan.code_graph", attr="refresh_code_graph")
    monkeypatch.setattr("tripll.plan.code_graph.kg_extra_available", lambda: False)
    db = tmp_path / "graph.db"
    assert refresh_code_graph(db, tmp_path) is False
    assert not db.exists()


def test_hash_agent_def_prefers_skw_agents() -> None:
    hash_agent_def = require_module("tripll.graphstore.task_sync", attr="hash_agent_def")
    info = hash_agent_def("wave-runner", REPO_ROOT)
    assert info is not None
    skw_path = REPO_ROOT / "src" / "tripll" / "skw" / "agents" / "wave-runner.md"
    assert skw_path.is_file()
