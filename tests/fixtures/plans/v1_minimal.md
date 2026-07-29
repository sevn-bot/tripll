# Demo Feature — v1 fixture

## Files in scope

| Subsystem | Paths |
|-----------|-------|
| Core | `src/tripll/demo/` |

## tripll execution graph

tripll_format: 1

| wave_id | title | depends_on | review_gate | effort | verify_targets |
|---------|-------|------------|-------------|--------|----------------|
| W0 | Design | | yes | M | make lint |
| W1 | Implement | W0 | | M | make check |
| Final | Gate | W1 | | L | make ci-resume |
