# claude-acc-manager — Architecture

An [arc42](https://arc42.org) description of the system, small enough to live in one file (sections 5–8 inline). Durable: this file and `docs/adr/` hold decisions and non-trivial knowledge, cite real sources of truth, and never cite `research_repos/` — see [ADR-0001](adr/0001-split-durable-decisions-from-ephemeral-build-evidence.md).

## 1. Introduction and goals

`cam` is a Linux-only CLI/TUI that manages, measures, and swaps Claude Code **OAuth subscription** accounts:

- `cam add <name>` — register an account by logging in at the source ([ADR-0004](adr/0004-login-at-source-via-claude-config-dir.md)); tokens are never copied.
- `cam list / status / usage` — per-account usage and limits (5h, 7d, model-scoped weeklies, resets).
- `cam switch [<name>] [--strategy best|next-available]` — manual or quota-driven swap of the login used by the plain `claude` command.
- `cam auto [--once|--interval|--threshold|--cooldown]` — unattended threshold-driven switching with anti-flap guards.

### Quality goals

| Goal | What it means here |
| --- | --- |
| Credential safety | Secrets never leave the machine except to `api.anthropic.com` / `platform.claude.com`; 0600/0700 + atomic writes; never in argv, logs, or error bodies (§8). |
| Measurement fidelity | Decisions consume real quota windows from the account's own endpoint, within a measured request budget — never guesses. |
| Race correctness | Swaps hold Claude Code's own mkdir locks so a live session's refresh never interleaves with a write (§6). |
| Local-first | No telemetry, no update checks, no third-party endpoints. |
| Minimal supply chain | One runtime dep (`textual`); stdlib for HTTP and CLI ([ADR-0002](adr/0002-python-uv-stdlib-urllib-argparse-textual-only-dep.md)). |

### Out of scope

macOS/keychain/menubar, Claude Desktop, session-history merging, directory mappings, aliases, export/import, API-key and setup-token accounts ([ADR-0005](adr/0005-oauth-subscription-accounts-only.md)), systemd unit packaging ([ADR-0006](adr/0006-auto-scope-one-shot-and-foreground-loop.md)), Secret Service storage ([ADR-0003](adr/0003-credentials-at-rest-under-xdg-with-private-modes.md)). Detail in §11.

---

## 2. Constraints

- **Linux only.** File-credential model (`~/.claude/.credentials.json`); no keychain paths.
- **OAuth subscription accounts only** ([ADR-0005](adr/0005-oauth-subscription-accounts-only.md)).
- **Stack locked**: Python ≥3.12 + uv; `textual` sole runtime dep; stdlib `urllib`/`argparse` ([ADR-0002](adr/0002-python-uv-stdlib-urllib-argparse-textual-only-dep.md)).
- **Strict TDD per commit** — coverage ≥95% branch + mutation gate ([ADR-0011](adr/0011-strict-tdd-per-commit-gate-coverage-and-mutation.md)).
- **Package-by-component** with import-linter contracts ([ADR-0010](adr/0010-package-by-component-import-linter-contracts.md)).
- **Usage endpoint budget**: ~28–30 req/h/identity for non-first-party clients — every fetch goes through `poll_policy` (§6).

---

## 3. Context and scope

```
                    ┌─────────────────────────────┐
  cam add ─────────►│ claude (CLAUDE_CONFIG_DIR=  │
                    │  <store>/accounts/<name>/)  │◄── interactive OAuth login
                    └─────────────────────────────┘
  cam switch/usage ─► ~/.claude/.credentials.json  ◄── read/write under
                    ~/.claude.json (oauthAccount)     claude-code's mkdir locks
                    └── api.anthropic.com ◄── /api/oauth/usage, /api/oauth/profile
                        platform.claude.com ◄── /v1/oauth/token (refresh)
```

| Partner | Direction | Interface |
| --- | --- | --- |
| `<secure-store>/.credentials.json` | we read/write | OAuth blob (`claudeAiOauth`: accessToken, refreshToken, expiresAt, scopes, subscriptionType, rateLimitTier; optional sibling `organizationUuid`); 0600. `<secure-store>` resolves `CLAUDE_SECURESTORAGE_CONFIG_DIR` (defined → verbatim, defined-empty → `~/.claude`) then `CLAUDE_CONFIG_DIR`, default `~/.claude` ([ADR-0014](adr/0014-credential-write-boundary.md)) |
| `~/.claude.json` | we splice | top-level `oauthAccount` identity; ~90 other keys must be preserved; path quirk: `~/.claude/.config.json` wins if it exists (legacy) |
| `api.anthropic.com /api/oauth/usage` | we GET | `Authorization: Bearer` + `anthropic-beta: oauth-2025-04-20` + UA; no `Content-Type` ([ADR-0007](adr/0007-honest-user-agent-per-endpoint-headers.md)) |
| `api.anthropic.com /api/oauth/profile` | we GET | same headers; identity oracle that classifies which account a credential belongs to |
| `platform.claude.com /v1/oauth/token` | we POST | RFC 6749 refresh grant, client_id `9d1c250a-e61b-44d9-88ed-5944d1962f5e`; `Content-Type` + UA, no `anthropic-beta` |
| claude-code process | we coexist with | mkdir locks `<secure-store>/.oauth_refresh.lock`, `<realpath(secure-store)>.lock` (60s staleness), `~/.claude.json.lock` (10s staleness), `<secure-store>/.storage-write` (15s staleness — held per credential mutation). Contract verified only on `[2.1.144, 2.2.0)` — mutating ops probe `claude --version` and refuse outside it ([ADR-0015](adr/0015-claude-version-contract-gate.md)) |

**Usage response contract** (undocumented; [ADR-0012](adr/0012-schema-tolerant-usage-model.md)): `five_hour`/`seven_day` `{utilization 0–100, resets_at}`; per-model weeklies only via `limits[]` entries carrying `scope.model.display_name`; ≤101 tolerated and saturated; unknown keys ignored; `extra_usage` present on the wire but unparsed. Percentages and reset epochs only — no absolute token counts. OAuth-only (API keys → 401).

**Refresh rotation**: one-time-use refresh tokens — both rotated tokens persist in one atomic write or the lineage strands ([ADR-0009](adr/0009-token-ownership-active-slot-never-refreshed.md); anthropics/claude-code#31021, #30930).

**Our storage** ([ADR-0003](adr/0003-credentials-at-rest-under-xdg-with-private-modes.md)) — `$XDG_DATA_HOME/claude-acc-manager/`: `accounts/<name>/` (each a real `CLAUDE_CONFIG_DIR` holding `.credentials.json` + `.claude.json`), `registry.json` (order, active pointer, enabled flags, quarantined lineages), `usage-cache.json` (last-good + 429 backoff per account), `settings.json` (threshold/interval/cooldown/hysteresis/strategy), `auto-state.json` (cooldown + no-return departure snapshot, under `.auto-state.lock`), `.lock` (registry flock), `.ops.lock` (operations flock — add/remove/switch hold it for their whole transaction, readers never take it; [ADR-0014](adr/0014-credential-write-boundary.md)). Dirs 0700, files 0600, all writes atomic via `shared/fsio.py`.

---

## 4. Solution strategy

| Problem | Approach | Decision |
| --- | --- | --- |
| Account onboarding without copying tokens | `CLAUDE_CONFIG_DIR` login-at-source | [ADR-0004](adr/0004-login-at-source-via-claude-config-dir.md) |
| Who refreshes which token | Claude Code owns the active slot; we refresh inactive accounts only, on demand | [ADR-0009](adr/0009-token-ownership-active-slot-never-refreshed.md) |
| Rate-limited, undocumented usage endpoint | Honest UA; per-endpoint headers; flat 429 backoff; last-good while `trust_ok` | [ADR-0007](adr/0007-honest-user-agent-per-endpoint-headers.md), [ADR-0008](adr/0008-flat-429-backoff-and-last-good-trust.md) |
| Drifting response shape | Schema-tolerant model of exactly the consumed keys | [ADR-0012](adr/0012-schema-tolerant-usage-model.md) |
| Layered structure that stays navigable | Package-by-component + import-linter contracts | [ADR-0010](adr/0010-package-by-component-import-linter-contracts.md) |
| No reviewer memory between sessions | Strict TDD, full gate per commit | [ADR-0011](adr/0011-strict-tdd-per-commit-gate-coverage-and-mutation.md) |
| Hermetic CLI tests | Transport-only `cli.py`; composition root in `__main__` | [ADR-0013](adr/0013-transport-only-cli-main-composition-root.md) |

---

## 5. Building blocks

```
src/claude_acc_manager/
  accounts/                  # the switching domain
    domain/                  entities.py · value_objects.py · oauth_identity.py
    application/ports.py     AccountStorePort · ActiveSlotPort · ClaudeLockPort
                             OpsLockPort · LoginLauncherPort · AccountDirReaderPort
                             AccountDirPort · UnclaimedCredentialPort · ClockPort
    application/use_cases/   add · remove · list · status  (switch/enable: M6)
    infrastructure/          file_account_store · active_slot · claude_locks
                             ops_lock · claude_login_launcher · account_dir_files
                             account_credential_store · path_resolver · system_clock
  usage/                     # the measurement domain
    domain/                  usage_snapshot · oauth_credential · resolved_identity
                             usage_cache_entry · services/{headroom, poll_policy,
                             cache_trust}
    application/ports.py     UsageApiPort · TokenRefresherPort · IdentityLookupPort
                             UsageCachePort · CredentialStorePort · ClockPort
    application/use_cases/   fetch_account_usage
    infrastructure/          anthropic_oauth · http_transport · file_usage_cache
                             system_clock
  shared/                    fsio.py (atomic private writes) · file_lock.py
  cli.py                     transport-only dispatch (ADR-0013)
  __main__.py                composition root (ADR-0013)
```

Structural rules are [ADR-0010](adr/0010-package-by-component-import-linter-contracts.md); `accounts` may import `usage`, never the reverse.

---

## 6. Runtime views

### Fetch one account's usage (`cam usage <name>` — shipped M5)

1. Fresh cache → serve without fetching.
2. Stale/absent cache → if the account is *inactive* and its token is expired, refresh first ([ADR-0009](adr/0009-token-ownership-active-slot-never-refreshed.md)); `invalid_grant` returns a permanent quarantine signal without hitting `/usage`.
3. GET usage → snapshot → persist cache → answer with a poll plan.
4. 429 → arm flat backoff, serve frozen last-good while `trust_ok` holds ([ADR-0008](adr/0008-flat-429-backoff-and-last-good-trust.md)); any other failure freezes last-good without arming the lockout.

### Switch transaction (M6)

Under `.ops.lock` (outermost — cam vs cam), then claude-code's `.oauth_refresh.lock` + `~/.claude.json.lock`; every `.credentials.json` mutation additionally holds `<secure-store>/.storage-write` for its write instant ([ADR-0014](adr/0014-credential-write-boundary.md)):

1. Back up the outgoing credential + `oauthAccount` into the outgoing account's slot — the identity oracle classifies an unattributable credential before anything is overwritten.
2. Read the target account's stored credential + `oauthAccount`.
3. Write target credentials to `~/.claude/.credentials.json` (atomic, 0600).
4. Splice target `oauthAccount` into `~/.claude.json`, preserving all other keys (salvage-copy + replace if torn).
5. Update `registry.json`.

Any failure rolls back in reverse. A running Claude Code picks up file-mode credentials on its next message.

### Strategy semantics (M6)

`headroom(account) = 100 − max(utilization of binding windows)` over 5h, 7d, and each active model-scoped weekly. `best`: switch only to a strictly-greater headroom; stay on unmeasurable current. `next-available`: registry order, skipping headroom ≤ 0. Disabled accounts and quarantined lineages are never candidates.

### Auto tick

`auto --once`: one check → maybe switch → exit (0 switched / 1 error / 2 no action / 3 blocked). `auto` loop: default 60s interval (min 15s), threshold 90% (50–99.9), cooldown 300s between proactive switches, hysteresis 10% on candidates, SIGTERM-clean. Every fetch respects the poll budget.

---

## 8. Cross-cutting concepts

### Credential-safety guarantees (each test-enforced)

1. Egress allowlist: `api.anthropic.com` + `platform.claude.com` only — enforced in `anthropic_oauth.py`'s `_require_allowed_host`, asserted by a unit test; no configurable base URLs.
2. No telemetry, no update checks, no third-party endpoints.
3. 0600/0700 + atomic writes everywhere via `shared/fsio.py`.
4. Secrets never in argv, logs, exceptions, or persisted error bodies — `AnthropicApiError` carries status + RFC 6749 error code only; redaction tests assert a token-shaped body never reaches `str(exc)`.
5. Hermetic tests: injected paths, clocks, transports; nothing touches real `$HOME`/`$XDG`/network.
6. Refuse to run as root (outside containers) — lands with M7's CLI.
7. Tears surface, never swallowed: a present-but-malformed JSON file raises rather than silently defaults.
8. Mutating/interoperating operations (add, switch, refresh, launch) refuse outside the verified claude band `[2.1.144, 2.2.0)` — probed per call at the narrowest unsafe op, overridable only per-run via `CAM_ASSUME_CLAUDE_CONTRACT`; read-only commands never probe ([ADR-0015](adr/0015-claude-version-contract-gate.md)).

### Identity oracle fails open

The profile GET resolves "which account owns this credential" before a switch overwrites anything; on any error it answers `None` and the caller treats the credential as unattributable — never a guessed identity.

---

## 9. Architecture decisions

| # | Decision |
| --- | --- |
| [0001](adr/0001-split-durable-decisions-from-ephemeral-build-evidence.md) | Split durable decisions from ephemeral build evidence |
| [0002](adr/0002-python-uv-stdlib-urllib-argparse-textual-only-dep.md) | Python + uv; stdlib urllib/argparse; `textual` the only runtime dep |
| [0003](adr/0003-credentials-at-rest-under-xdg-with-private-modes.md) | Credentials at rest: 0600/0700 under XDG, atomic writes |
| [0004](adr/0004-login-at-source-via-claude-config-dir.md) | Onboarding is login-at-source via `CLAUDE_CONFIG_DIR` |
| [0005](adr/0005-oauth-subscription-accounts-only.md) | OAuth subscription accounts only |
| [0006](adr/0006-auto-scope-one-shot-and-foreground-loop.md) | Auto scope: strategies + `--once` + foreground loop; no systemd |
| [0007](adr/0007-honest-user-agent-per-endpoint-headers.md) | Honest `User-Agent`; per-endpoint header sets |
| [0008](adr/0008-flat-429-backoff-and-last-good-trust.md) | Flat 429 backoff; last-good while `trust_ok` holds |
| [0009](adr/0009-token-ownership-active-slot-never-refreshed.md) | Never refresh the active slot; atomic rotation persist; `invalid_grant` quarantines |
| [0010](adr/0010-package-by-component-import-linter-contracts.md) | Package-by-component with import-linter contracts |
| [0011](adr/0011-strict-tdd-per-commit-gate-coverage-and-mutation.md) | Strict TDD; per-commit gate; 95% branch + mutmut |
| [0012](adr/0012-schema-tolerant-usage-model.md) | Schema-tolerant usage model; `extra_usage` deferred |
| [0013](adr/0013-transport-only-cli-main-composition-root.md) | Transport-only `cli.py`; `__main__` composition root |
| [0014](adr/0014-credential-write-boundary.md) | Credential writes mirror claude's `.storage-write`; `.ops.lock` serializes add/remove/switch |
| [0015](adr/0015-claude-version-contract-gate.md) | Mutating ops require the verified claude band `[2.1.144, 2.2.0)`; `CAM_ASSUME_CLAUDE_CONTRACT` overrides |

---

## 10. Quality requirements

### The development loop

Strict TDD: red → green → refactor; test + implementation land in one conventional commit (`type(scope): imperative`, enforced by commit-msg). One logical change per commit; nothing committed red — the pytest-in-pre-commit gate makes a red commit mechanically impossible ([ADR-0011](adr/0011-strict-tdd-per-commit-gate-coverage-and-mutation.md) for the full hook order).

### Standing thresholds

Branch coverage ≥95% (enforced) · mutation: zero disqualifying mutants (`survived|no tests|suspicious|timeout|segfault|not checked`) · xenon `--max-absolute B --max-modules B --max-average A` · radon `cc_min A` · pyright strict · bandit `-ll` · vulture min-confidence 80 · deptry · import-linter contracts · tests hermetic (§8.5), Triple-A, named fakes, `test/` mirrors `src/` · `-m integration` opt-in only.

### Commit protocol

Conventional commits; scope = component or concern (`feat(accounts):`, `fix(usage):`, `docs(adr):`). Milestone gate measurements go in the closing commit's body — never in a doc ([ADR-0001](adr/0001-split-durable-decisions-from-ephemeral-build-evidence.md)).

---

## 11. Risks and technical debt

| Risk | Evidence | Mitigation |
| --- | --- | --- |
| `/api/oauth/usage` is undocumented and can change | open upstream requests for an official surface (anthropics/claude-code#44328, #32796) | schema-tolerant parsing ([ADR-0012](adr/0012-schema-tolerant-usage-model.md)); `-m integration` smoke test re-verifies shape |
| 429 wall | non-first-party budget ~28–30 req/h; the wall does not recover (anthropics/claude-code#31637, #30930) | poll policy constants measured under that regime; flat backoff + last-good ([ADR-0008](adr/0008-flat-429-backoff-and-last-good-trust.md)) |
| UA requirement tightened | the UA-bucket behavior could change (anthropics/claude-code#31021) | single UA constant; honest identity ([ADR-0007](adr/0007-honest-user-agent-per-endpoint-headers.md)) |
| Refresh-token stranding | one-time-use rotation (anthropics/claude-code#31021, #30930) | atomic dual persist; never refresh active; `invalid_grant` quarantine ([ADR-0009](adr/0009-token-ownership-active-slot-never-refreshed.md)) |

### Deferred (not debt — gated on a real consumer)

`extra_usage` parsing ([ADR-0012](adr/0012-schema-tolerant-usage-model.md)) · Secret Service storage ([ADR-0003](adr/0003-credentials-at-rest-under-xdg-with-private-modes.md)) · systemd packaging ([ADR-0006](adr/0006-auto-scope-one-shot-and-foreground-loop.md)). Full list with owners: `maintainer/backlog.md` → Deferred and watched.
