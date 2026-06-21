# build-plan-from-errors — turn problem taxonomy

The driver appends this template to every **build-plan-from-errors** dispatch. Before
grouping failures or writing waves, classify **every** turn in `{{ERROR_TURN_IDS}}` against
**every** problem kind below. A turn may have multiple kinds; mark each row `yes` or `no` with
evidence.

---

## Problem kinds

| id | name | description | what to look for | evidence required |
|----|------|-------------|------------------|-------------------|
| `log_error` | Log error | ERROR/CRITICAL logs, exceptions, stack traces | `--stream log`; `--errors-only`; `--grep 'ERROR\|CRITICAL\|Traceback'` | Log line with level + message; include line ref or grep pattern |
| `log_warning` | Log warning | WARNING logs indicating degraded behaviour (not benign noise) | `--stream log --grep 'WARNING'`; compare with operator intent | Warning line + why it matters for this turn |
| `trace_error` | Trace error | Failed executor/triage spans, non-ok span status | `--stream trace`; meta `terminal_status`; span `status` in `error`/`failed`/`denied`/`cancelled`/`escalated` | Span name + status + key attrs (tier, tool, executor) |
| `no_answer` | No answer | Operator message with no substantive bot reply | `--stream message`: last user role without following assistant; log `executor_no_answer`; empty assistant body; timeout markers | Message id/role sequence or log substring |
| `wrong_answer` | Wrong answer | Bot replied but answer is wrong, off-topic, hallucinated, or contradicts operator intent | Full `--stream message` (operator vs assistant); compare to user ask and session context | Operator excerpt + assistant excerpt showing mismatch |
| `wrong_tool_use` | Wrong tool use | Wrong tool, bad args, tool error, unnecessary tool loop, permission denial | Message `tool_call` / tool result rows; trace tool spans; log tool errors | Tool name, args snippet, error text or span |
| `triage_routing` | Triage routing | Wrong tier/route (B vs C), bad escalation, triage miss | Trace triage/executor spans; tier attrs; escalation logs | Span or log showing chosen vs expected route |
| `channel_delivery` | Channel delivery | Reply not delivered, partial send, adapter failure | Log channel adapter errors; message send failures; missing outbound after assistant | Log line or trace channel span failure |
| `terminal_failure` | Terminal failure | Turn ended with terminal error from meta | `--section meta` `terminal_status` in `error` (or other failure enum) | Meta `terminal_status` value |
| `other` | Other | Anything else material with evidence | Any stream when no row above fits but operator impact exists | Free-text description + pointer |

---

## Per-turn checklist (required)

Fill one row per `(turn_id, problem_type)`. Use `present` = `yes` | `no`. When `yes`, the
`evidence` column must cite bundle stream + locator (message index, log grep, span name).

| turn_id | problem_type | present | evidence |
|---------|--------------|---------|----------|
| *(copy for each turn × each kind above)* | | | |

**Rules:**

1. Do **not** skip a turn or a problem kind — every cell must be `yes` or `no`.
2. `no` rows need no evidence; leave `evidence` blank or `-`.
3. Prefer concrete pointers (`message#3 assistant`, `log grep 'executor_no_answer'`, `span executor.tier_b status=error`).
4. Carry this table (or equivalent markdown) into the wave plan as **`## Turn problem matrix`** before remediation waves.

---

## Stream hints by kind

| kind | primary streams | useful commands |
|------|-----------------|-----------------|
| `log_error`, `log_warning` | log | `sevn turn-bundle view <id> --stream log --grep '<pat>'` |
| `trace_error`, `triage_routing`, `wrong_tool_use` | trace, log | `sevn turn-bundle view <id> --stream trace` |
| `no_answer`, `wrong_answer`, `wrong_tool_use` | message | `sevn turn-bundle view <id> --stream message` |
| `channel_delivery` | log, trace | adapter/channel span names in trace |
| `terminal_failure` | meta | `sevn turn-bundle view <id> --section meta` |

Cross-check all three streams (log, message, trace) before marking a kind `no`.
