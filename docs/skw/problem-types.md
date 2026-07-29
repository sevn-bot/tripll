# skw — code-quality problem taxonomy

Before grouping findings or writing waves, classify **every** changed module on the branch
against **every** problem kind below. A file may have multiple kinds; mark each row `yes` or
`no` with evidence taken from the thermo-nuclear review.

## Problem kinds

| id | name | what to look for | evidence required |
|----|------|------------------|-------------------|
| `oversized_file` | Oversized file (1k rule) | File over ~1000 lines, or one the branch pushes further over | Path + line count (e.g. `1561` lines) |
| `god_object` | God object / god module | One class/module owns unrelated responsibilities (parse + I/O + validate + orchestrate) | Class/module name + the distinct responsibilities |
| `spaghetti` | Spaghetti control flow | Deep nesting, duplicated branch matrices, asymmetric paths that should be unified | `file:line` of each divergent branch |
| `duplication` | Duplication | Copy-pasted logic, parallel implementations, repeated regex/parse sets across modules | Each path + the duplicated symbol/region |
| `leaky_abstraction` | Leaky abstraction | Feature logic via magic metadata keys, circular-import workarounds, monkey-patching | `file:line` + the leak mechanism |
| `weak_typing` | Weak typing at boundaries | Ubiquitous `dict[str, Any]` for structured payloads; runtime-only validation in hot paths | Symbol + where a typed model belongs |
| `dead_noise` | Dead / noise code | Unused enum variants, always-`True` readiness stubs, unenforced version constants, narrating comments | `file:line` of the dead/noise item |
| `missed_code_judo` | Missed code-judo | The high-leverage move that deletes the most code was not taken (one parser/two emitters, one policy object, thin adapter/fat module, parallelize) | Description + the modules it would simplify |
| `constitution_violation` | Constitution violation | Branch conflicts with a **MUST** principle in [`constitution.md`](constitution.md) (spec-kit standard) — e.g. behavioral change without tests, new dependency, unsafe path handling | Principle id + `file:line` of the conflict |
| `state_lifecycle` | Unsafe shared state | Module-global mutable state with no TTL/eviction/locking; multi-worker unsafe | Symbol + the lifecycle gap |
| `other` | Other | Any maintainability concern not above | Free-text description + pointer |

## Per-file checklist (required)

Fill one row per `(file, problem_type)`. Use `present` = `yes` | `no`. When `yes`, `evidence`
must cite path + locator (line range or symbol).

| file | problem_type | present | evidence |
|------|--------------|---------|----------|
| *(copy for each changed file × each kind above)* | | | |

**Rules:**

1. Do **not** skip a file or a problem kind — every cell must be `yes` or `no`.
2. `no` rows need no evidence; leave it blank or `-`.
3. Prefer concrete pointers (`telegram_rich.py:1231-1362`, `RichCapability.UNKNOWN`,
   `_VIEWER_STREAMS`).
4. Carry this table into the wave plan as **`## Code-quality problem matrix`** before the
   remediation waves.

## Severity hints

| severity | typical kinds |
|----------|---------------|
| critical | `oversized_file` (new 1k+), `god_object`, `state_lifecycle`, `constitution_violation` (MUST) |
| high | `duplication`, `leaky_abstraction`, `spaghetti` |
| medium | `weak_typing`, repeated boilerplate |
| low | `dead_noise`, comment trimming |

Sequence behavior-preserving extractions (high-value, low-risk) before structural rewrites.
