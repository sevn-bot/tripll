"""Deterministic AST extractors — confidence 1.0, file:line evidence (W1.3)."""

from __future__ import annotations

from pathlib import Path

from tests.conftest import require_module

_FIXTURE = Path(__file__).parent / "fixtures" / "extract_pkg"


def test_declares_imports_calls_on_fixture() -> None:
    extract_module = require_module("tripll.extract.ast_python", attr="extract_module")
    result = extract_module(_FIXTURE / "sample.py", repo="tripll", sha="abc")
    predicates = {e["predicate"] for e in result["edges"]}
    assert {"DECLARES", "IMPORTS", "CALLS"} <= predicates


def test_covers_edge_from_test_fixture() -> None:
    extract_module = require_module("tripll.extract.ast_python", attr="extract_module")
    extract_tests = require_module("tripll.extract.tests_cov", attr="extract_tests")
    mod = extract_module(_FIXTURE / "sample.py", repo="tripll", sha="abc")
    tests = extract_tests(_FIXTURE / "test_sample.py", repo="tripll", sha="abc")
    predicates = {e["predicate"] for e in mod["edges"] + tests["edges"]}
    assert "COVERS" in predicates


def test_deterministic_confidence_and_evidence() -> None:
    extract_module = require_module("tripll.extract.ast_python", attr="extract_module")
    result = extract_module(_FIXTURE / "sample.py", repo="tripll", sha="abc")
    for node in result.get("nodes", []):
        assert node["confidence"] == 1.0
        assert ":" in node["evidence"]
    for edge in result["edges"]:
        assert edge["confidence"] == 1.0
        assert ":" in edge["evidence"]
