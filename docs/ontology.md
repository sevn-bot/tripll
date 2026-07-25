# Code KG ontology and extraction metrics

Authoritative ontology: `src/tripll/ontology/ontology.yaml`.

## Extraction pipeline (W3)

Deterministic extractors run first (`ast_python`, `tests_cov`, `specs_docs`, `make_ci`) with
`confidence = 1.0` and `evidence = file:line`. Semantic predicates (`IMPLEMENTS`, `ABOUT`) use
batched CLI adapter turns only — no in-process LLM or API keys (P6).

CLI entry points:

```bash
tripll graph extract [--repo tripll] [--sha HEAD] [--db .tripll/graph.db]
tripll graph fuse [--db .tripll/graph.db]
tripll graph gate [--predicate IMPLEMENTS] [--precision 0.95]
tripll graph query <node_id> [--hops 2] [--at-sha …]
```

## §15.2 — IMPLEMENTS pass on tripll (2026-07-25)

Measured on branch `wave/code-factory-l1` @ W3 against the tripll checkout itself:

| Metric | Value |
|--------|-------|
| Wall-clock (deterministic extract, 137 `.py` files) | ~14 s |
| Nodes / edges (deterministic) | 3971 / 3313 |
| Semantic batch turns (`--semantic`, stub mode) | 1 turn (offline stub; batched CLI path verified) |
| Quality gate threshold | precision ≥ 0.90 on 50-item sample |

Re-run after changing semantic prompts or rules; never patch the graph to pass the gate.

## Ontology drift

Unmodelled repeated relations accumulate in the `candidate_relations` side table. Promotion to
`ontology.yaml` is a reviewed act with a version bump — never auto-accepted.
