"""Ontology loader — predicates, vague verbs, competency questions (W1.2)."""

from __future__ import annotations

import pytest

from tests.conftest import require_module


def test_ontology_yaml_loads() -> None:
    load_ontology = require_module("tripll.ontology.types", attr="load_ontology")
    ont = load_ontology()
    assert "layers" in ont
    for layer in ("code", "task", "finding"):
        assert layer in ont["layers"]


def test_every_predicate_has_domain_and_range() -> None:
    load_ontology = require_module("tripll.ontology.types", attr="load_ontology")
    validate_predicates = require_module("tripll.ontology.types", attr="validate_predicates")
    ont = load_ontology()
    errors = validate_predicates(ont)
    assert errors == []


@pytest.mark.parametrize("verb", ["RELATED_TO", "HAS_LINK"])
def test_vague_verbs_rejected(verb: str) -> None:
    validate_predicate_name = require_module(
        "tripll.ontology.types", attr="validate_predicate_name"
    )
    with pytest.raises(ValueError, match=r"vague|rejected|forbidden"):
        validate_predicate_name(verb)


def test_competency_questions_traversable() -> None:
    load_competency_questions = require_module(
        "tripll.ontology.types", attr="load_competency_questions"
    )
    questions = load_competency_questions()
    assert len(questions) == 10
    for q in questions:
        assert q.get("traversal") or q.get("sql_hint")
