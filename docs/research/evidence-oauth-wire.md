# Porting evidence — OAuth wire contract and machine facts

**Ephemeral.** This is the construction evidence behind the durable contract in `docs/architecture.md §3`: every `research_repos/` `path:line` citation lives here, not in durable docs ([ADR-0001](../adr/0001-split-durable-decisions-from-ephemeral-build-evidence.md)). Deleted when M9 ships; whatever is still true then belongs in an ADR or a code comment.

Sources: `research_repos/claude-swap` v0.27.0b1 (Python, MIT) and `research_repos/ai-usagebar` v1.14.0 (Rust, MIT), both read in full; the two independent implementations agree on every wire contract below.

## Verified on this machine (2026-09-10)

| Fact | Measurement |
| --- | --- |
| Claude Code | `claude 2.1.267` at `~/.local/bin/claude` |
| OAuth credentials | `~/.claude/.credentials.json` exists, mode 0600, keys: `claudeAiOauth` (`accessToken, refreshToken, expiresAt, refreshTokenExpiresAt, scopes, subscriptionType, rateLimitTier`), sibling `organizationUuid` |
| Identity config | `~/.claude.json` top-level `oauthAccount` (`emailAddress, accountUuid, organizationUuid, organizationName, userRateLimitTier, …`) alongside ~90 machine-local keys that must be preserved |
| Subscription | `subscriptionType: pro`, `rateLimitTier: default_claude_ai` |
| Toolchain | Python 3.14.4, uv 0.11.8, pre-commit 4.6.1 installed globally; ruff/bandit/radon/xenon/vulture/deptry/pyright NOT global → pinned uv dev-deps |

## Usage endpoint

`GET https://api.anthropic.com/api/oauth/usage` — `Authorization: Bearer <accessToken>`, `anthropic-beta: oauth-2025-04-20`, non-empty custom `User-Agent` (ADR-0007 settled *which* UA).

> **M4 correction (2026-09-10, source re-read directly).** This section originally claimed both references agree a `claude-code/<version>` UA is load-bearing. They do not. ai-usagebar spoofs `claude-code/2.1.183` (`src/anthropic/fetch.rs:22`, CHANGELOG 0.7.2). claude-swap's `oauth.py` sends its own honest `claude-swap/1.0` on all three calls — `git log -S"User-Agent"` shows commit `ee2563c` (2026-04-03) added that literal to the usage GET **and** the refresh POST in one change, fixing a real 403. What is load-bearing is *a non-empty custom UA*. claude-swap `usage_store.py:120` names the consequence — "the usage endpoint enforces a request budget on non-first-party User-Agents" — and its `poll_policy.py` constants were measured under that non-spoofed regime. `cam` therefore sends `claude-acc-manager/<version>` and stays inside the non-first-party budget. Also corrected: **headers are per-endpoint, not uniform** — usage GET sends no `Content-Type`; refresh POST and profile GET send no `anthropic-beta`. The M4 `-m integration` smoke test confirmed a live 200 with the honest UA.

Response shape (claude-swap `oauth.py` `build_usage_result`, ai-usagebar `src/anthropic/types.rs` + `tests/fixtures/anthropic_usage_full.json`):

```json
{
  "five_hour":         { "utilization": 62.0, "resets_at": "2026-05-23T13:30:00Z" },
  "seven_day":         { "utilization": 27.0, "resets_at": "2026-05-27T13:00:00Z" },
  "seven_day_sonnet":  { "utilization": 4.0,  "resets_at": "..." },
  "seven_day_opus":    null,
  "extra_usage":       { "is_enabled": true, "monthly_limit": 5000,
                         "used_credits": 250.0, "currency": "USD", "decimal_places": 2 },
  "limits": [
    { "kind": "session",       "group": "session", "percent": 10, "severity": "normal" },
    { "kind": "weekly_all",    "group": "weekly",  "percent": 55, "severity": "normal" },
    { "kind": "weekly_scoped", "group": "weekly",  "percent": 84, "severity": "warning",
      "resets_at": "...", "scope": { "model": { "display_name": "Fable" } } }
  ]
}
```

- `utilization`/`percent` are 0–100 floats; ≤101 accepted (rounding slack), saturated to 100 (ai-usagebar `types.rs`).
- `seven_day_sonnet`/`_opus` are **not** distinctly modelled by either reference (ai-usagebar's `UsageResponse` has no `seven_day_opus`; its fixture smuggles `"tangelo": null` to prove unknown keys are ignored). Per-model weeklies come **only** from `limits[]` entries carrying `scope.model.display_name` — keyed on that shape, never on `limits[].kind` (ADR-0012).
- `extra_usage.monthly_limit` may be `null` (uncapped; ai-usagebar issue #30). `extra_usage` is unparsed by `cam` — no consumer (ADR-0012).
- OAuth-only: API keys → 401 (claudeops-tui `docs/oauth-usage-endpoint.md`; verified by claude-swap's account-type gating).

## Token refresh

`POST https://platform.claude.com/v1/oauth/token` — `Content-Type: application/json`, custom UA, **no** `anthropic-beta`:

```
{ "grant_type": "refresh_token", "client_id": "9d1c250a-e61b-44d9-88ed-5944d1962f5e", "refresh_token": "..." }
→ { "access_token": ..., "refresh_token"?: ..., "expires_in": ... }
```

Identical client id and flow in claude-swap `oauth.py:19-20,169-186`, ai-usagebar `src/anthropic/oauth.rs:15-18,72-90`, and community reports (anthropics/claude-code#31021, #30930). Refresh tokens are one-time use → both rotated tokens persist atomically in one write (ADR-0009). `invalid_grant` = permanently dead lineage → quarantine (claude-swap `autoswitch.py`).

## Identity oracle

`GET https://api.anthropic.com/api/oauth/profile` (same auth/beta headers) — resolves which account a credential belongs to (claude-swap `oauth.py:282`); used to classify the outgoing credential during a switch.

## Polling budget (measured)

- claude-swap `poll_policy.py`: ~28–30 req/h/identity for non-first-party UAs; the tool self-limits to ~1 req/3min (`SERVE_TTL_S=180`, `MIN_INTERVAL_S=180`, urgent 60s, exhausted 600s, ±10% jitter).
- anthropics/claude-code#31637: third-party pollers at 30–60s hit an unrecoverable 429 wall (ladder 30→60→120→240→300s; `retry-after: 0` while still limited, #30930).
- #31021: same token, same moment — no UA → 429, `User-Agent: claude-code/2.1.72` → 200. Buckets are per-UA.

## Switching mechanics

claude-swap `switcher.py` `_perform_switch:6684`, `claude_locks.py`, `credentials.py`:

- Single active login: `~/.claude/.credentials.json` + `oauthAccount` spliced into `~/.claude.json` (all other keys preserved).
- Safe swap holds claude-code's own locks — proper-lockfile-compatible mkdir locks: `~/.claude/.oauth_refresh.lock`, `~/.claude.lock` (60s staleness), `~/.claude.json.lock` (10s staleness).
- Transaction order: backup outgoing into its owning slot → read target → write target → splice `oauthAccount` → update registry; rollback in reverse.
- Post-switch, a running Claude Code picks up file-mode credentials on its next message (`_print_switch_followup:7258`).
- `~/.claude.json` path quirk: `~/.claude/.config.json` if it exists (legacy), else `$HOME/.claude.json` (claude-swap `paths.py:42`).

ai-usagebar `account.rs` `switch_cli_account` (`src/account.rs:788`+): also swaps the plain-`claude` default login, with `--dry-run` and outgoing-credential capture back into the named account — a second, independent implementation of the same transaction.

## Per-account isolation (`CLAUDE_CONFIG_DIR`)

ai-usagebar `docs/claude-accounts.md` + `src/account.rs`: `account add` launches `claude` with `CLAUDE_CONFIG_DIR=<dir>`; login lands directly there. Operational rule: "never run two clients against copies of the same refresh token."

**M0 probe — DONE (2026-09-10, claude 2.1.267):** scratch `CLAUDE_CONFIG_DIR=/tmp/claude-probe`, real OAuth login, keys-only inspection. `.credentials.json` and `.claude.json` both land **inside** `$CLAUDE_CONFIG_DIR` (0600) — matching claude-swap `paths.py:42-53` for the env-set branch. Fresh login's `.credentials.json` has **only** `claudeAiOauth` (no sibling `organizationUuid`) — the sibling on long-lived credentials is optional. Legacy `<config_home>/.config.json` fallback not exercised (no legacy file here); kept from claude-code source evidence. A scratch config dir also sprouts `backups/`, `cache/`, `sessions/`, `settings.json` — an account store dir is a real CLAUDE_CONFIG_DIR and will contain these.

## Toolchain conventions provenance (user's datastudio repo)

`~/Documents/repos/datastudio` measured 2026-09-10: component practice `identity` 20 files/367 lines, `chat` 98 files/7,536 lines (~77 lines/file); ruff py312 line-length 100 select `D,E,W,F,I,B,UP,N` google pydocstyle (`D` ignored in tests); pyright strict; bandit `-r src -ll`; vulture min-confidence 80; xenon `--max-absolute B --max-modules B --max-average A`; radon `cc_min A`; deptry; pre-commit `language: system` local hooks via `uv run`; pins `pytest==9.1.0`, `pytest-cov==7.1.0`; test tree mirrors src, scoped classes, Triple-A markers, behavior-statement names.

## Structural failure modes measured in the references (why not flat)

| Repo | Layout | Cost |
| --- | --- | --- |
| claude-swap | flat `src/claude_swap/*.py` | `switcher.py` 7,431 lines; `autoswitch.py` 2,364; `cli.py` 1,494 |
| ai-usagebar | mostly flat `src/*.rs` | `config.rs` 4,392; `tui/panels.rs` 2,635; `claude_desktop/mod.rs` 1,606 |
| datastudio `chat` | layered package-by-component | 98 files / 7,536 lines, ~77/file — no god files |
