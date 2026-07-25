# Code KG ontology — three layers

Authoritative schema: `src/tripll/ontology/ontology.yaml`
Competency questions: `src/tripll/ontology/competency.md`

## Layers

### `code` — target repository (commit-scoped)

| Kind | Natural key | Predicates (sample) |
|------|-------------|---------------------|
| `Module` | `<repo>#<path>` | `DECLARES`, `IMPORTS`, `OWNS` |
| `Symbol` | `<repo>#<path>::<qualname>` | `CALLS`, `IMPLEMENTS` |
| `Test` | `<repo>#<path>::<testname>` | `COVERS` |
| `Spec` / `Requirement` | `<repo>#<path>` / `<repo>#<spec>::<FR-id>` | `SPECIFIES` |
| `MakeTarget` / `CIcheck` | `<repo>#make:<name>` / `<repo>#check:<name>` | `VERIFIES`, `RUNS` |

Extractors: `src/tripll/extract/` (`ast_python`, `tests_cov`, `specs_docs`, `make_ci`, semantic fuse).

### `task` — run execution graph

Replaces flat `graph.json` over time; written **alongside** the ledger (D6).

Kinds: `Plan`, `Wave`, `Attempt`, `Gate`, `VerifyRun`, `Branch`, `PullRequest`, `AgentDef`,
`PromptDef`, `ModelRef`, `EnvFingerprint`.

Predicates: `PART_OF`, `DEPENDS_ON` (typed `reason`), `TARGETS`, `DISPATCHED`, `GRADED_BY`, …

Sync: `src/tripll/graphstore/task_sync.py`

### `finding` — CI and review outcomes

| Kind | Source |
|------|--------|
| `Finding` | GitHub check-runs, review comments, verifier output |

Predicates: `ABOUT` (→ symbol), `RAISED_BY`, `FIXED_BY`, `SUPERSEDES`.

Ingestion: `src/tripll/github/` · CLI: `tripll findings sync|list|triage`

## Provenance (mandatory)

Every node and edge carries: `source`, `extractor`, `extractor_version`, `confidence`,
`extracted_at`, `evidence`. Unmodelled relations accumulate in `candidate_relations` until
promoted via reviewed ontology bump.

## CLI

```bash
tripll graph extract [--repo .] [--db .tripll/graph.db]
tripll graph fuse
tripll graph gate --predicate IMPLEMENTS --precision 0.90
tripll graph query <node_id> [--hops 2]
```

See [`graph-serving.md`](graph-serving.md) for brief packing and D23 verdict.
