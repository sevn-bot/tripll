"""Load and validate the three-layer ontology."""

from __future__ import annotations

import re
from importlib.resources import files
from typing import Any

import yaml  # type: ignore[import-untyped]


def _ontology_path() -> str:
    return str(files("tripll.ontology").joinpath("ontology.yaml"))


def load_ontology() -> dict[str, Any]:
    """Load ``ontology.yaml`` from the package."""
    with open(_ontology_path(), encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError("ontology.yaml must be a mapping")
    return data


def validate_predicate_name(name: str) -> None:
    """Reject vague or forbidden predicate names."""
    ont = load_ontology()
    vague = {str(v).upper() for v in ont.get("vague_verbs", [])}
    if name.upper() in vague:
        raise ValueError(f"vague verb rejected: {name}")


def validate_predicates(ont: dict[str, Any] | None = None) -> list[str]:
    """Return validation errors for predicate domain/range coverage."""
    data = ont if ont is not None else load_ontology()
    errors: list[str] = []
    layers = data.get("layers")
    if not isinstance(layers, dict):
        return ["ontology missing layers mapping"]
    all_kinds: set[str] = set()
    for layer in layers.values():
        if isinstance(layer, dict) and isinstance(layer.get("kinds"), dict):
            all_kinds.update(layer["kinds"].keys())
    for layer_name, layer in layers.items():
        if not isinstance(layer, dict):
            errors.append(f"layer {layer_name!r} is not a mapping")
            continue
        kinds = layer.get("kinds", {})
        preds = layer.get("predicates", {})
        if not isinstance(preds, dict):
            errors.append(f"layer {layer_name!r} missing predicates")
            continue
        kind_names = set(kinds.keys()) if isinstance(kinds, dict) else set()
        for pred_name, spec in preds.items():
            try:
                validate_predicate_name(str(pred_name))
            except ValueError as exc:
                errors.append(str(exc))
                continue
            if not isinstance(spec, dict):
                errors.append(f"predicate {pred_name!r} in {layer_name} is not a mapping")
                continue
            domain = spec.get("domain")
            range_ = spec.get("range")
            if not domain or not range_:
                errors.append(f"predicate {pred_name!r} missing domain or range")
            elif domain not in kind_names:
                errors.append(f"predicate {pred_name!r} domain {domain!r} not in kinds")
            elif range_ not in all_kinds:
                errors.append(f"predicate {pred_name!r} range {range_!r} not in kinds")
    return errors


def load_competency_questions() -> list[dict[str, Any]]:
    """Parse competency questions from ``competency.md``."""
    text = files("tripll.ontology").joinpath("competency.md").read_text(encoding="utf-8")
    match = re.search(r"```yaml\s*\n(.*?)```", text, re.DOTALL)
    if not match:
        raise ValueError("competency.md missing yaml question block")
    block = yaml.safe_load(match.group(1))
    if not isinstance(block, dict):
        raise ValueError("competency question block must be a mapping")
    questions = block.get("questions")
    if not isinstance(questions, list):
        raise ValueError("competency questions must be a list")
    return [q for q in questions if isinstance(q, dict)]
