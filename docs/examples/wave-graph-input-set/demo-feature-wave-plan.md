# Demo feature — example wave graph

**Purpose:** Typical multi-wave v1 plan used to demonstrate the HTML wave graph. Regenerate the
committed diagram with:

```bash
tripll validate docs/examples/wave-graph-input-set --graph-html docs/examples/wave-graph.html
```

The graph is a diamond: a Pre-0 review gate, a tests-first wave, two parallel implementation
waves, and a final integration gate.

## Files in scope

| Subsystem | Paths |
|-----------|-------|
| Renderer | `src/tripll/graph_html.py` |
| Tests | `tests/test_graph_html.py` |

## tripll execution graph

tripll_format: 1

| wave_id | title | depends_on | review_gate | effort | verify_targets | model | role |
|---------|-------|------------|-------------|--------|----------------|-------|------|
| W0 | Design + Pre-0 decisions | | yes | S | make lint | | impl |
| W1 | Author test suite | W0 | | M | make lint, make test | | test-author |
| W2 | Implement renderer | W1 | | M | make ci-affected | | impl |
| W3 | Implement CLI flag | W1 | | S | make ci-affected | | impl |
| Final | Integrate + gate | W2, W3 | | L | make ci-resume | | impl |

---

## Wave W0 — Design + Pre-0 decisions (review gate)

- [ ] **W0.1** Confirm node/edge shape and layout rules with the operator.

## Wave W1 — Author test suite (test-author)

- [ ] **W1.1** RED tests for layout depth and edge count.

## Wave W2 — Implement renderer

- [ ] **W2.1** Turn W1 tests green; do not edit `tests/`.

## Wave W3 — Implement CLI flag

- [ ] **W3.1** Emit the artifact on successful validation.

## Wave Final — Integrate + gate

- [ ] **Final.1** Run the pre-merge gate and integrate the batch.
