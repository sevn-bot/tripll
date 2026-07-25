# Codex (ChatGPT subscription) OAuth for sevn LLM transports — wave plan

**Status:** Wave W4 done 2026-06-27 (CLI PKCE login, MC reauth, onboarding ChatGPT OAuth, auth_mode schema); Wave W5 pending
**Date:** 2026-06-27

```toml
waveorch_format = 2
title  = "Codex (ChatGPT subscription) OAuth for sevn LLM transports"
slug   = "codex-oauth-subscription"
base   = "test-pre"
branch = "feature/codex-oauth-subscription"

[pipeline]
max_turns = 3

[pipeline.run]
agent = "wave-runner"
prompt = "prompts/wave-runner.md"

[pipeline.review]
agent = "reviewer"
prompt = "prompts/reviewer.md"

[pipeline.review.inputs]
plugin = "thermo"

[pipeline.generate]
agent = "post-review-wave-generator"
prompt = "prompts/post-review-wave-generator.md"

[[waves]]
id = "W0"
title = "Design + flow investigation + scaffolding"
depends_on = []
review_gate = true
effort = "M"
role = "impl"
verify = ["make lint", "make typecheck"]

[[waves]]
id = "W1"
title = "Tests for Codex OAuth (RED)"
depends_on = ["W0"]
effort = "M"
role = "test-author"
verify = ["make lint", "make typecheck"]

[[waves]]
id = "W2"
title = "OAuth core — PKCE login, callback, token exchange, credential model"
depends_on = ["W1"]
effort = "M"
role = "impl"
verify = ["make ci-affected"]

[[waves]]
id = "W3"
title = "Token lifecycle + proxy bearer/account-id injection"
depends_on = ["W2"]
effort = "M"
role = "impl"
verify = ["make ci-affected"]

[[waves]]
id = "W4"
title = "CLI + Mission Control + onboarding + config surfaces"
depends_on = ["W2"]
effort = "M"
role = "impl"
verify = ["make ci-affected"]

[[waves]]
id = "W5"
title = "Validation, doctor, schema + docs"
depends_on = ["W3", "W4"]
effort = "M"
role = "impl"
verify = ["make ci-affected"]

[[waves]]
id = "Final"
title = "Integration gate"
depends_on = ["W5"]
effort = "L"
role = "impl"
verify = ["make ci-resume"]
```

## Goal

Let an operator authenticate sevn's OpenAI transport with a **ChatGPT Plus/Pro/Team
subscription** via OpenAI's **Codex OAuth (PKCE)** flow — the same legitimate,
OpenAI-sanctioned flow OpenClaw uses (`https://docs.openclaw.ai/concepts/oauth`) — instead
of a pay-as-you-go `sk-` API key. sevn already has the **receiving structures**: a provider
registry (`src/sevn/config/sections/providers.py`), per-request proxy credential resolution
(`src/sevn/proxy/credentials.py`, `src/sevn/proxy/app.py`), a secret store/cache
(`src/sevn/security/secrets/`), and a `consumption_type = "subscription"` concept. The
**OAuth login + token mint/refresh + bearer injection** does not exist yet — the
`sevn providers oauth login` command (`src/sevn/cli/commands/providers_cmd.py:144`) only
prints a manual-paste stub, and the `codex` id under `src/sevn/coding_agents/` is an unrelated
deferred coding-agent executor stub. This plan ports the flow.

## Background — what exists vs what's missing

| Capability | State today | File |
|------------|-------------|------|
| Provider registry + `consumption_type=subscription` | exists | `src/sevn/config/sections/providers.py:127` |
| Per-request proxy credential resolution (binding → bucket → env) | exists | `src/sevn/proxy/credentials.py` (`resolve_request_credential`, `_resolve_api_key`) |
| Proxy header injection (`authorization: Bearer …` for OpenAI route) | exists | `src/sevn/proxy/app.py:252` |
| Secret store get/put/delete + `${SECRET:…}` expansion + TTL cache | exists | `src/sevn/security/secrets/{chain,value_expand,cache}.py` |
| `sevn providers oauth login/status/logout` | **stub** (prints paste instructions) | `src/sevn/cli/commands/providers_cmd.py:144` |
| Codex PKCE flow, token mint, **token refresh**, account-id usage | **missing** | — (this plan) |
| `codex` coding-agent executor | unrelated stub | `src/sevn/coding_agents/executors/__init__.py:62` |

## W0 investigation — pre-answered from source (2026-06-27)

The five original Open Questions were resolved by reading OpenAI's Codex flow and two
reference implementations (see **Reference implementations** below). **Confirmed constants
(from `openai/codex`, as used verbatim by the `opencode-openai-codex-auth` plugin):**

| Item | Value |
|------|-------|
| `client_id` | `app_EMoamEEZ73f0CkXaXp7hrann` (public Codex client) |
| Authorize URL | `https://auth.openai.com/oauth/authorize` |
| Token URL | `https://auth.openai.com/oauth/token` |
| Redirect URI | `http://localhost:1455/auth/callback` (server binds `127.0.0.1:1455`) |
| PKCE | S256 (`code_challenge` + `code_challenge_method=S256`) |
| Scope | `openid profile email offline_access` |
| Extra authorize params | `id_token_add_organizations=true`, `codex_cli_simplified_flow=true`, `originator=codex_cli_rs` |
| Code→token grant | `grant_type=authorization_code` + `client_id, code, code_verifier, redirect_uri` (form-urlencoded) |
| Refresh grant | `grant_type=refresh_token` + `refresh_token, client_id` |
| Token response | `{ access_token, refresh_token, expires_in }` → store `{access, refresh, expires=now+expires_in*1000}` |
| `accountId` extraction | base64-decode JWT payload of `access_token`; read `["https://api.openai.com/auth"].chatgpt_account_id`; **fail if absent** |

**Model-call endpoint (resolves original Open Q1 — the decisive finding):** Codex OAuth tokens
do **not** call `api.openai.com/v1/chat/completions`. They call the **ChatGPT backend Responses
API**:

- Full endpoint: `https://chatgpt.com/backend-api/codex/responses` (the plugin rewrites the
  Responses path segment "responses" → "codex/responses").
- Required headers: `Authorization: Bearer <access>`, `chatgpt-account-id: <accountId>`,
  `OpenAI-Beta: responses=experimental`, `originator: codex_cli_rs`, `accept: text/event-stream`
  (SSE), and `x-api-key` **removed**. Optional `session_id` / `conversation_id`.
- Required body fields: `store = false` (mandatory on the ChatGPT backend), `instructions =
  <Codex system prompt>`, and `include: ["reasoning.encrypted_content"]` for stateless operation.

**Consequence for scope:** this is the **Responses API**, a different request/response schema
from sevn's current OpenAI chat-completions route — so sevn needs a **new Codex transport/route
with request↔response translation**, not a base-URL + bearer swap. This is the heavy lift and is
loaded into **W3**.

**Caveats recorded:** (a) the scope is identity-only by design — Codex access is gated by the
`chatgpt-account-id` + the backend endpoint, not extra OAuth scopes; (b) the token endpoint returns
`403 unsupported_country_region_territory` in unsupported regions; (c) the official Codex CLI
stores the token plaintext at `~/.codex/auth.json` — sevn instead stores it in the encrypted
secrets chain at alias `oauth.openai`; (d) this is OpenAI's sanctioned external-tool flow, not a
scraping bridge.

## Reference implementations

| Source | Use |
|--------|-----|
| `openai/codex` (official CLI) | Canonical client_id, endpoints, headers, body contract |
| `numman-ali/opencode-openai-codex-auth` (`lib/auth/auth.ts`, `lib/auth/server.ts`, `lib/request/fetch-helpers.ts`, `lib/constants.ts`) | Closest portable HTTP-transport reference (PKCE flow, callback server, `createCodexHeaders`, codex/responses path rewrite, `store=false`) |
| `EvanZhouDev/openai-oauth` | Secondary cross-check (responses/transport) |
| OpenClaw | Routes via the **native Codex app-server harness** instead of direct HTTP — the *rejected* alternative for sevn (see W0.2) |

## One architectural decision still open for the W0 gate

**Direct Responses transport vs. spawning the Codex app-server.** OpenClaw shells out to the
native Codex runtime; the opencode plugin reimplements the Responses HTTP transport. sevn is an
HTTP **egress proxy**, so the direct Responses transport (port of the opencode plugin) is the
natural fit — but it requires chat-completions↔Responses translation.

### W0.2 resolution (D7 — confirmed 2026-06-27)

**Chosen:** **Direct Responses HTTP transport** (opencode-openai-codex-auth style) — target
`https://chatgpt.com/backend-api/codex/responses`, inject subscription headers, translate
chat-completions↔Responses in W3.

**Rejected:** Codex app-server subprocess (OpenClaw style) — adds native-runtime coupling,
does not fit sevn's HTTP egress-proxy model, and prevents centralized token refresh (D3) /
credential isolation in the proxy layer.

**Evidence:** `src/sevn/security/oauth/design.py` (`LOCKED_DECISIONS["D7"]`), constants in
`src/sevn/security/oauth/constants.py` (`CODEX_RESPONSES_*`).

## Decisions baked into this plan (confirm/adjust at W0 gate)

| # | Topic | Decision |
|---|-------|----------|
| D1 | Auth selector | `providers.openai.auth_mode ∈ {api_key, oauth}` (default `api_key`, fully back-compat). `oauth` makes the proxy resolve a bearer from the OAuth credential **and route to the Codex Responses transport** (`https://chatgpt.com/backend-api/codex/responses`) with the `chatgpt-account-id`/`OpenAI-Beta`/`originator` headers and `store=false` body contract, instead of `api_key` on the chat-completions route. |
| D7 | Transport approach | **Confirmed W0.2:** port the **direct Responses HTTP transport** (opencode-plugin style), not the Codex app-server subprocess (OpenClaw style) — fits sevn's egress-proxy model. W3 builds chat-completions↔Responses translation + route. |
| D2 | Credential storage | OAuth credential stored as a JSON blob at secret alias `oauth.openai` (reuse `oauth.<provider>` scheme already in `providers_cmd.py`); resolved via the existing secrets chain/cache. No raw token in `sevn.json`. |
| D3 | Refresh ownership | The **proxy** refreshes the access token before expiry under an async lock and persists the rotated `{access,refresh,expires}` back to the store (token-sink behavior). Agents never see the token (D8 of the providers plan still holds). |
| D4 | Back-compat | When `auth_mode` is unset/`api_key`, behavior is byte-for-byte today's resolution path; no regression for `sk-`/`SEVN_PROVIDER_API_KEY`/MiniMax configs. |
| D5 | Headless fallback | Local callback on `127.0.0.1:1455`; when binding fails or `--headless`, print the authorize URL and accept a pasted redirect URL/code. |
| D6 | Surfaces | `sevn providers oauth login/status/logout --provider openai` drive the real flow; Mission Control Providers panel exposes reauth; onboarding wizard offers "Sign in with ChatGPT". |

## Files in scope

| Subsystem | Paths |
|-----------|-------|
| OAuth core (new) | `src/sevn/security/oauth/` (PKCE, authorize URL, callback server, token client, credential model) |
| Provider config | `src/sevn/config/sections/providers.py`, `infra/sevn.schema.json`, `src/sevn/data/sevn_config_long_description.json` |
| Proxy resolution + refresh | `src/sevn/proxy/credentials.py`, `src/sevn/proxy/app.py`, `src/sevn/proxy/settings.py` |
| Secret store glue | `src/sevn/security/secrets/` (read/write `oauth.openai` blob) |
| CLI | `src/sevn/cli/commands/providers_cmd.py` |
| Mission Control + onboarding | `src/sevn/ui/dashboard/api/`, `src/sevn/ui/spa/dashboard/app.js`, `src/sevn/onboarding/` |
| Docs/specs | `specs/05-llm-transports.md`, `specs/06-secrets.md`, `specs/02-config-and-workspace.md`, `about-sevn.bot/…` |
| Tests | `tests/security/`, `tests/proxy/`, `tests/config/`, `tests/cli/` |

**W0.1 drift check (2026-06-27):** No drift in core OAuth constants vs.
`numman-ali/opencode-openai-codex-auth` `lib/auth/auth.ts` and upstream `openai/codex` references.
All rows in the constants table above match current source. **Cosmetic only:** some third-party
clients vary the `originator` query/header value (`codex_cli_rs` vs `opencode` vs `pi`); sevn
locks `codex_cli_rs` per the opencode plugin reference.

## Wave W0 — design + flow investigation + scaffolding (review gate)

- [x] **W0.1** Confirm the pre-answered constants table against current `openai/codex` + the `opencode-openai-codex-auth` source (client_id, URLs, scope, PKCE, token/refresh grants, `accountId` JWT claim) — flag any drift since 2026-06-27. (2026-06-27 ✅: verified vs opencode `lib/auth/auth.ts` + `lib/constants.ts`; no core drift; originator cosmetic variance only)
- [x] **W0.2** **Resolve the one open architectural decision (D7):** confirm the direct Responses HTTP transport (recommended) vs. the Codex app-server subprocess. This sets W3 scope. (2026-06-27 ✅: D7 direct Responses HTTP transport confirmed; app-server rejected — see W0.2 resolution + `src/sevn/security/oauth/design.py`)
- [x] **W0.3** Lock the design: `auth_mode` selector (D1), `oauth.openai` blob shape (D2), proxy-owned refresh-under-lock (D3), back-compat path (D4), headless fallback (D5), surfaces (D6). (2026-06-27 ✅: `src/sevn/security/oauth/design.py` LOCKED_DECISIONS D1–D7 + plan decisions table)
- [x] **W0.4** Scaffold empty modules/signatures only (no behavior): `src/sevn/security/oauth/` package skeleton + the `auth_mode`/credential fields on the provider config model; ensure `make lint` and `make typecheck` pass on the skeleton. (2026-06-27 ✅: `src/sevn/security/oauth/{constants,design,credential,pkce,authorize,callback,token_client}.py`, `ProviderEntryConfig.auth_mode`, `resolve_auth_mode`)
- [x] **W0.5** **Review gate:** operator sign-off on D7 and the locked decisions before any impl/test wave runs. (2026-06-27 ✅: operator approved W0 gate; W1 test-author dispatched)

## Wave W1 — tests for Codex OAuth (test-author, RED)

- [x] **W1.1** Tests for PKCE generation (verifier/challenge/state) and authorize-URL construction under `tests/security/`. (2026-06-27 ✅: `tests/security/oauth/test_pkce.py`, `test_authorize.py`)
- [x] **W1.2** Tests for token-exchange response parsing → `{access, refresh, expires, accountId}` credential model (incl. `accountId` extraction from the access token). (2026-06-27 ✅: `tests/security/oauth/test_token_client.py`)
- [x] **W1.3** Tests for credential persistence + round-trip through the secret store at alias `oauth.openai`. (2026-06-27 ✅: `tests/security/oauth/test_credential_store.py`)
- [x] **W1.4** Tests for refresh-on-expiry under lock: expired token triggers refresh, rotated token persisted, no double-refresh under concurrency. (2026-06-27 ✅: `tests/security/oauth/test_refresh_lock.py`)
- [x] **W1.5** Proxy tests under `tests/proxy/`: `auth_mode=oauth` targets `chatgpt.com/backend-api/codex/responses`, injects `Bearer <access>` + `chatgpt-account-id` + `OpenAI-Beta: responses=experimental` + `originator`, removes `x-api-key`, and enforces `store=false` body; and **does not regress** `api_key`/bucket/`SEVN_PROVIDER_API_KEY` chat-completions paths. (2026-06-27 ✅: `tests/proxy/test_codex_oauth_transport.py`)
- [x] **W1.9** Translation tests: a sevn internal turn round-trips through chat-completions↔Responses (incl. SSE streaming) for the Codex transport. (2026-06-27 ✅: `tests/proxy/test_codex_translation.py`)
- [x] **W1.6** Provider-resolution tests: `auth_mode=oauth` selects the OAuth credential over `providers.openai.api_key`; precedence and default `api_key` back-compat asserted. (2026-06-27 ✅: `tests/config/test_providers_auth_mode.py`)
- [x] **W1.7** CLI tests for `sevn providers oauth login/status/logout --provider openai` (status shows expiry/account; logout deletes the alias). (2026-06-27 ✅: `tests/cli/test_providers_oauth_openai.py`)
- [x] **W1.8** Doctor/validate tests: missing/expired `oauth.openai` for an OAuth-mode assigned slot is flagged (non-fatal in validate). (2026-06-27 ✅: `tests/config/test_validate_openai_oauth.py`)

## Wave W2 — OAuth core (impl)

- [x] **W2.1** Implement PKCE + authorize-URL builder and the credential model in `src/sevn/security/oauth/` (product code only; no test authoring). (2026-06-27 ✅: `src/sevn/security/oauth/pkce.py`, `authorize.py`, `credential.py`; tests/security/oauth/test_pkce.py + test_authorize.py green)
- [x] **W2.2** Implement the local callback server (`127.0.0.1:1455/auth/callback`) with the manual paste-redirect fallback (D5). (2026-06-27 ✅: `src/sevn/security/oauth/callback.py` — `start_local_callback_server`, `parse_pasted_oauth_redirect`)
- [x] **W2.3** Implement the token-exchange client (`https://auth.openai.com/oauth/token`) and `accountId` extraction; map response → credential model. (2026-06-27 ✅: `src/sevn/security/oauth/token_client.py`; tests/security/oauth/test_token_client.py green)
- [x] **W2.4** Implement persistence of the credential blob to secret alias `oauth.openai` via the secrets chain; ensure W1.1–W1.3 go green. (2026-06-27 ✅: `src/sevn/security/oauth/storage.py`; tests/security/oauth/test_credential_store.py green; W1.1–W1.3 28/28 pass)

## Wave W3 — token lifecycle + proxy integration (impl)

- [x] **W3.1** Implement refresh-before-expiry under an async lock with token-sink persistence (D3): on near-expiry, POST `grant_type=refresh_token` to `https://auth.openai.com/oauth/token`, rotate `{access, refresh, expires}`, persist back to `oauth.openai`; single-flight under concurrency. (2026-06-27 ✅: `src/sevn/proxy/oauth_lifecycle.py`; tests/security/oauth/test_refresh_lock.py 4/4 pass)
- [x] **W3.2** Add the **Codex Responses transport/route**: target `https://chatgpt.com/backend-api/codex/responses`, inject `Authorization: Bearer <access>`, `chatgpt-account-id: <accountId>`, `OpenAI-Beta: responses=experimental`, `originator: codex_cli_rs`, `accept: text/event-stream`; remove `x-api-key`; enforce body `store=false` + `instructions` + `include:["reasoning.encrypted_content"]` (port `createCodexHeaders` / codex/responses path rewrite from the reference plugin). (2026-06-27 ✅: `src/sevn/proxy/codex_transport.py`, `src/sevn/proxy/app.py`; tests/proxy/test_codex_oauth_transport.py)
- [x] **W3.3** Implement chat-completions↔Responses request/response (incl. SSE) translation so sevn's internal turn schema round-trips through the Codex endpoint; wire it in `src/sevn/proxy/app.py` for `auth_mode=oauth` requests. (2026-06-27 ✅: `src/sevn/proxy/codex_translation.py`; tests/proxy/test_codex_translation.py 9/9 pass)
- [x] **W3.4** Extend `src/sevn/proxy/credentials.py` so `auth_mode=oauth` resolves a live bearer + accountId (refreshing as needed) ahead of the `api_key`/bucket/env chain; preserve all back-compat ordering (D4). Wire `auth_mode` + OAuth fields through `src/sevn/config/sections/providers.py` and `src/sevn/proxy/settings.py`; turn W1.4–W1.6 green. (2026-06-27 ✅: `resolve_oauth_request_credential` + `_async`; tests/config/test_providers_auth_mode.py W1.6)

## Wave W4 — CLI + Mission Control + onboarding + config (impl)

- [x] **W4.1** Replace the `sevn providers oauth login` stub (`src/sevn/cli/commands/providers_cmd.py:144`) with the real PKCE flow for `--provider openai` (local callback + headless paste fallback); update `status` to show expiry/account and `logout` to clear `oauth.openai`. (2026-06-27 ✅: `src/sevn/security/oauth/login_flow.py`, `providers_cmd.py`; tests/cli/test_providers_oauth_openai.py W1.7 3/3 xpass)
- [x] **W4.2** Add Mission Control Providers reauth/login affordance (`src/sevn/ui/dashboard/api/`, `src/sevn/ui/spa/dashboard/app.js`) hitting the existing `POST /api/v1/providers/{provider}/oauth/reauth` handoff. (2026-06-27 ✅: `system.py` authorize_url handoff, `app.js` Sign in / Re-auth button)
- [x] **W4.3** Add an onboarding-wizard "Sign in with ChatGPT (Codex OAuth)" option under `src/sevn/onboarding/` that drives W4.1; turn W1.7 green. (2026-06-27 ✅: `openai_oauth.py`, `web_app.py` /api/openai/oauth/*, `web_wizard/index.html` + `app.js`)
- [x] **W4.4** Document `providers.openai.auth_mode` in `infra/sevn.schema.json` + `src/sevn/data/sevn_config_long_description.json` and regenerate schema via `make config-schema`. (2026-06-27 ✅: provider_registry_entry.auth_mode + long_description; make config-schema green)

## Wave W5 — validation, doctor, schema + docs (impl)

- [ ] **W5.1** Add a `sevn doctor` / `sevn config validate` probe that flags an OAuth-mode openai slot with a missing/expired `oauth.openai` credential, with a `doctor --fix` reauth prompt; turn W1.8 green.
- [ ] **W5.2** Update specs: `specs/05-llm-transports.md` (Codex transport/route), `specs/06-secrets.md` (`oauth.openai` blob), `specs/02-config-and-workspace.md` (`auth_mode`).
- [ ] **W5.3** Update `about-sevn.bot/…` provider docs and run any README drift gate (`make readme-check`).
- [ ] **W5.4** Confirm `make ci-affected` green across config/proxy/security/cli paths.

## Wave Final — integration gate (impl)

- [ ] **Final.1** Run `make ci-resume` to green; resolve any failing step in order until "all steps passed".
- [ ] **Final.2** Manual live smoke: `sevn providers oauth login --provider openai`, then a real turn routed through an OpenAI/Codex model slot in `auth_mode=oauth`, confirming no `sk-` key is configured.
