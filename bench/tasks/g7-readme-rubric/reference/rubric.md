# README operator section rubric (G7 bench)

Score each dimension 0–10. Pass when all dimensions are ≥ 7.

| Dimension | Bar |
|-----------|-----|
| command_accuracy | Make/uv commands match the Makefile targets |
| first_run_clarity | A new operator can bootstrap without tribal knowledge |
| safety_callouts | Git-clean guard and secret handling are visible |
| scope_honesty | Docs do not promise features the repo lacks |

Reference operator blurb:

```markdown
## Operator quick start

Run `make setup` once, then `tripll doctor` before the first dispatch.
Never run `git clean -x` — it deletes local run state under `runs/`.
```
