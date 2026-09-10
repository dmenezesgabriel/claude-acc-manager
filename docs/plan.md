# claude-acc-manager — Implementation Plan

Linux-only CLI/TUI to manage, measure, and swap Claude Code OAuth subscription
accounts. Every element below is grounded in measured evidence from the two
reference repos, the live machine, and public Anthropic issue tracker data —
sources are cited inline. Nothing in this plan is an assumption; where a fact
could not be verified yet, it appears as an explicit M0 verification task.

## 1. Objective

- `cam add <name>` — register an account by logging in at the source (never
  copying tokens).
- `cam list / status / usage` — per-account usage and limits (5h, 7d,
  model-scoped weeklies, resets) in CLI and TUI.
- `cam switch [<name>] [--strategy best|next-available]` — manual or
  quota-driven swap of the login used by the plain `claude` command.
- `cam auto [--once|--interval|--threshold|--cooldown]` — unattended
  threshold-driven switching with anti-flap guards.
- Credentials never leave the machine except to official Anthropic endpoints
  (`api.anthropic.com`, `platform.claude.com`).

## 2. Evidence base

### 2.1 Verified on this machine (2026-09-10)

| Fact | Measurement |
|---|---|
| Claude Code | `claude 2.1.267` at `~/.local/bin/claude` |
| OAuth credentials | `~/.claude/.credentials.json` exists, mode 0600, keys: `claudeAiOauth` (`accessToken, refreshToken, expiresAt, refreshTokenExpiresAt, scopes, subscriptionType, rateLimitTier`), sibling `organizationUuid` |
| Identity config | `~/.claude.json` top-level `oauthAccount` (`emailAddress, accountUuid, organizationUuid, organizationName, userRateLimitTier, ...`) alongside machine-local state (`projects`, `userID`, ~90 other keys that must be preserved) |
| Subscription | `subscriptionType: pro`, `rateLimitTier: default_claude_ai` |
| Toolchain | Python 3.14.4, uv 0.11.8, pre-commit 4.6.1 installed globally; ruff/bandit/radon/xenon/vulture/deptry/pyright NOT installed globally → all come as pinned uv dev-dependencies |
| No git repo yet | working dir is not a repository; M0 initializes it |

### 2.2 Verified in reference source code

claude-swap v0.27.0b1 (`research_repos/claude-swap`, Python, MIT) and
ai-usagebar v1.14.0 (`research_repos/ai-usagebar`, Rust, MIT) were read in
full; two independent implementations agree on every wire contract below.

**Usage endpoint (undocumented; also used by Claude Code's own `/usage`):**

```
GET https://api.anthropic.com/api/oauth/usage
Authorization: Bearer <claudeAiOauth.accessToken>
anthropic-beta: oauth-2025-04-20
User-Agent: <a non-empty custom UA>   # required; see the M4 correction below
```

> **M4 correction (2026-09-10, source re-read directly).** The line above
> originally read `User-Agent: claude-code/<version>  # LOAD-BEARING` and this
> section claimed both reference repos agree on that. They do **not**.
> ai-usagebar spoofs `claude-code/2.1.183` (`src/anthropic/fetch.rs:22`,
> CHANGELOG 0.7.2). claude-swap's `oauth.py` sends its own honest
> `claude-swap/1.0` on **all three** calls — `git log -S"User-Agent"` shows
> commit `ee2563c` ("fix oauth refresh 403 by adding User-Agent header",
> 2026-04-03) added that literal to the usage GET **and** the refresh POST in
> one change, fixing a real 403; unchanged in production since. What is
> actually load-bearing is *a non-empty custom UA*, not the `claude-code`
> string. claude-swap `usage_store.py:120` names the consequence — "the usage
> endpoint enforces a request budget on non-first-party User-Agents" — and its
> `poll_policy.py` constants (already adopted in §2.2 below) were measured
> under that non-spoofed regime. `cam` therefore sends `claude-acc-manager/
> <version>` and stays inside the non-first-party budget, keeping the polling
> evidence consistent. Also corrected: **headers are per-endpoint, not
> uniform** — usage GET sends no `Content-Type`; the refresh POST and the
> profile GET send no `anthropic-beta` (each `cam` adapter sends exactly the
> set its claude-swap counterpart does). The M4 `-m integration` smoke test
> confirmed a live 200 with the honest UA.

Response (claude-swap `oauth.py` `build_usage_result`, ai-usagebar
`src/anthropic/types.rs` + `tests/fixtures/anthropic_usage_full.json`):

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

- `utilization`/`percent` are 0–100 floats; values ≤ 101 accepted (rounding
  slack), saturated to 100 (ai-usagebar `types.rs`).
- **M4 correction:** `seven_day_sonnet` / `seven_day_opus` are *not* distinctly
  modelled by either reference (ai-usagebar's `UsageResponse` has no
  `seven_day_opus` field; its own fixture smuggles a `"tangelo": null` key to
  prove unknown top-level keys are ignored). Per-model weekly windows come
  **only** from `limits[]` entries carrying a `scope.model.display_name` —
  keyed on that shape, never on `limits[].kind`. `cam`'s
  `usage_snapshot_from_response` models exactly `five_hour`, `seven_day`, and
  the scoped `limits[]` windows; every other key is tolerated and ignored.
- `extra_usage` is documented here as the live wire shape but is **not parsed
  by `cam` yet** — no milestone through the switch strategies consumes spend
  (claude-swap excludes it from headroom as "a separate axis"), so it will be
  added when a real consumer exists, not speculatively.
- `extra_usage.monthly_limit` may be `null` (uncapped, ai-usagebar issue #30).
- Percentages and reset timestamps only — no absolute token counts exist on
  this endpoint.
- OAuth-only: API keys are rejected 401 (claudeops-tui
  `docs/oauth-usage-endpoint.md` documents this; verified by claude-swap's
  account-type gating).

**Token refresh (RFC 6749 grant; official Claude CLI client id):**

```
POST https://platform.claude.com/v1/oauth/token
Content-Type: application/json
User-Agent: <a non-empty custom UA>       # NO anthropic-beta (M4 correction:
                                          # claude-swap oauth.py sends none here)
{ "grant_type": "refresh_token",
  "client_id": "9d1c250a-e61b-44d9-88ed-5944d1962f5e",
  "refresh_token": "..." }
→ { "access_token": ..., "refresh_token"?: ..., "expires_in": ... }
```

- Identical client id and flow in claude-swap `oauth.py:19-20,169-186`,
  ai-usagebar `src/anthropic/oauth.rs:15-18,72-90`, and community reports
  (anthropics/claude-code#31021, #30930).
- **Refresh tokens are one-time use**: both rotated tokens must be persisted
  atomically in the same write, or the lineage is stranded (#31021, #30930).
- `invalid_grant` = permanently dead lineage → account must be quarantined
  from auto-pick (claude-swap `autoswitch.py`).

**Identity oracle:**

```
GET https://api.anthropic.com/api/oauth/profile   (same auth/beta headers)
```

Resolves which account a credential belongs to (claude-swap `oauth.py:282`,
used to classify the outgoing credential during a switch).

**Polling budget (measured, not guessed):**

- claude-swap `poll_policy.py`: the usage endpoint allows ~28–30 requests/hour
  per identity for non-first-party user agents; the tool self-limits to
  ~1 request/3 min average (`SERVE_TTL_S=180`, `MIN_INTERVAL_S=180`, urgent
  60s near threshold, exhausted 600s, ±10% jitter).
- anthropics/claude-code#31637: third-party pollers at 30–60s intervals hit a
  429 wall that does not recover (ladder 30→60→120→240→300s stuck; no usable
  `Retry-After`; #30930 reports `retry-after: 0` while still limited).
- #31021 (proof, same token, same moment): without `User-Agent` → 429; with
  `User-Agent: claude-code/2.1.72` → 200. Rate-limit buckets are per
  User-Agent. ai-usagebar pins `claude-code/2.1.183` and documents the header
  as load-bearing (`src/anthropic/fetch.rs:17-22`).

**Switching mechanics (claude-swap `switcher.py` `_perform_switch:6684`,
`claude_locks.py`, `credentials.py`):**

- Claude Code holds a single active login: credentials at
  `~/.claude/.credentials.json` (Linux), identity spliced as the `oauthAccount`
  section of `~/.claude.json` (all other keys preserved).
- A safe swap must hold claude-code's own locks, reimplemented as
  proper-lockfile-compatible mkdir locks: `~/.claude/.oauth_refresh.lock`,
  `~/.claude.lock` (60s staleness), `~/.claude.json.lock` (10s staleness).
  Without this, a live session's token refresh interleaves with the swap.
- Transaction order: backup outgoing credential into its owning slot → read
  target → write target credentials to active location → splice `oauthAccount`
  → update registry; rollback in reverse on failure.
- Post-switch, a running Claude Code picks up file-mode credentials on its next
  message (claude-swap `_print_switch_followup:7258`).
- `~/.claude.json` path quirk: `~/.claude/.config.json` if it exists (legacy),
  else `$HOME/.claude.json` — `.claude.json` sits at homedir, not inside
  `~/.claude/` (claude-swap `paths.py:42`).

**Per-account isolation (`CLAUDE_CONFIG_DIR`):**

- ai-usagebar `docs/claude-accounts.md` + `src/account.rs`: `account add`
  launches `claude` with `CLAUDE_CONFIG_DIR=<dir>`; the login lands directly
  in that directory (`<dir>/.credentials.json` on Linux) — tokens are never
  copied at add time. Documented operational rule: "Never run two clients
  against copies of the same refresh token" — rotation eventually strands one
  copy.
- **M0 verification task — DONE (empirical probe, 2026-09-10, claude 2.1.267):**
  launched `claude` in a scratch `CLAUDE_CONFIG_DIR=/tmp/claude-probe` with a real
  OAuth login and inspected the landing (key names only, values never read).
  Measured: `.credentials.json` and `.claude.json` both land **inside**
  `$CLAUDE_CONFIG_DIR` (modes 0600) — matching claude-swap `paths.py:42-53` for
  the env-set branch; the default-profile case (`$HOME/.claude.json` at homedir,
  credentials at `~/.claude/.credentials.json`) confirmed by the pre-existing
  files on this machine. A fresh login's `.credentials.json` contains **only**
  the `claudeAiOauth` key (no sibling `organizationUuid`) — the sibling seen on
  the user's long-lived credentials is optional and must be treated as such in
  the M2 active-slot adapter. The legacy `<config_home>/.config.json` fallback
  was not exercised (no legacy file exists here); kept from claude-code source
  evidence, flagged for M2 fixture coverage. A scratch config dir also sprouts
  `backups/`, `cache/`, `sessions/`, `settings.json` — an account store dir is a
  real CLAUDE_CONFIG_DIR and will contain these; layout (§4.3) already accounts
  for it.

- **M1 exit gate — DONE (measured, 2026-09-10):** all 17 pre-commit hooks green
  on `--all-files` in 8.5s wall (full mutation pass included: 397/397 mutants
  killed, `mutmut results` empty, ~14s). One in-band exclusion exists: a
  `# pragma: no mutate` on fsio's `.encode("utf-8")` (codec alias equivalence,
  justification in-band) and on the two JSON-narrowing `cast()` helpers in
  file_account_store (cast is a runtime no-op — mutants of its type argument
  are equivalent by construction). Measured mutmut facts recorded for later
  milestones: mutmut 3.7.0 skips decorated classes/functions entirely, so
  domain logic lives in module-level functions with dataclass shells; the
  incremental test→function mapping misses newly-created functions (mutants
  show "no tests") until a full rebuild (`rm -rf mutants`), which is needed
  after structural refactors.

- **M3 exit gate — DONE (measured, 2026-09-10):** all 17 pre-commit hooks green
  on `--all-files` in ~88s wall; unit suite 227 passing, 100.00% branch
  coverage; full mutation pass 851/851 mutants killed (`mutmut results` empty,
  ~20s). Delivered: `oauth_identity` (pure `oauthAccount` parser, shared by
  `add` + `status`), `system_clock`/`ClockPort`, the `add`/`remove`/`list`/
  `status` use cases, `test/support/` named fakes (`InMemoryAccountStore` &c.),
  and a minimal `cam` CLI — `cli.run` is transport-only argparse dispatch,
  `claude_acc_manager.__main__` is the composition root (the sole importer of
  concrete adapters; a new import-linter contract enforces the split). New
  exclusions, each justified in-band: `__main__` is out of the coverage floor
  and `mutmut do_not_mutate` (its one ambient `os.environ`/`Path.home()` read
  cannot run hermetically — `build_use_cases` is still covered for real by
  `test/unit/test_main.py`). Two defects found and fixed during integration,
  each with a regression test: the `cam` entry point still named the pre-split
  `cli:main`; `fsio.ensure_private_dir` chmod'd the first *existing* ancestor
  it walked past (would silently tighten `~/.local/share` to 0700 on first
  run). `pytest` path now includes `test/` for the shared fakes. `add`'s live
  login is still interactive-only; the add→list→status→remove round-trip was
  validated end-to-end through the real `FileAccountStore`/`ActiveSlotAdapter`/
  `AccountDirReader` with a scripted login capture.

- **M4 exit gate — DONE (measured, 2026-09-10):** all 17 pre-commit hooks green
  on `--all-files` (~2 min wall on an idle machine); unit suite 300 passing,
  100.00% branch coverage on the new `usage` component; full mutation pass
  1162/1162 killed (`mutmut results` empty). Delivered the `usage` component:
  `usage_snapshot` + `resolved_identity` (pure, schema-tolerant parsers),
  `HttpTransportPort`/`HttpResponse`/`HttpTransportError` + `UrllibHttpTransport`
  (stdlib `urllib` behind a thin injectable seam, tested against a loopback
  `http.server`), and `anthropic_oauth` — three adapters (`AnthropicUsageApi`,
  `AnthropicTokenRefresher`, `AnthropicIdentityLookup`) implementing
  `UsageApiPort` / `TokenRefresherPort` / `IdentityLookupPort`, driven in tests
  by the new `FakeHttpTransport` named fake. Five new import-linter contracts
  (usage layering + "usage never imports accounts"). Safety guarantees:
  `_require_allowed_host` gates every request against the two-host allowlist;
  `AnthropicApiError` carries only status + the RFC 6749 `error` code, never
  the body (redaction tests assert a token-shaped body never reaches
  `str(exc)`); the identity oracle fails open to `None` on any error
  (claude-swap parity). Corrections to §2.2 recorded inline above: the
  User-Agent is honest (`claude-acc-manager/<version>`), not a `claude-code`
  spoof; header sets are per-endpoint; `seven_day_sonnet`/`_opus` and
  `extra_usage` are not modelled. New `-m integration` smoke test
  (`test/integration/`, opt-in via `pytest -m integration`, `addopts` now
  `-m "not integration"`, `testpaths = ["test"]`) run once by hand against the
  real endpoint — a live 200 with the honest UA, `five_hour` present. Observed
  flake, not a defect: under heavy CPU load `mutmut` can mark two pre-existing
  `shared/fsio._write_all` mutants `timeout` (dynamic-timeout baseline
  miscalibration on an `os.write` loop); idle runs are clean 1162/1162.

### 2.3 Verified in user's own conventions (datastudio, `~/Documents/repos/datastudio`)

| Fact | Measurement |
|---|---|
| Component practice | `identity`: 20 files / 367 lines (full entities/value_objects/ports/use_cases/infrastructure tree at ~18 lines/file — deliberate uniform surface); `chat`: 98 files / 7,536 lines (~77 lines/file); `shared` component for cross-cutting code |
| Toolchain in practice | ruff (py312, line-length 100, select `D,E,W,F,I,B,UP,N`, google pydocstyle, `D` ignored in tests), pyright **strict** (`typeCheckingMode = "strict"`), bandit `-r src -ll`, vulture `--min-confidence 80`, xenon `--max-absolute B --max-modules B --max-average A`, radon `cc_min A`, deptry with documented ignore codes, pre-commit with `language: system` local hooks via `uv run` |
| Exact pins practiced | `pytest==9.1.0`, `pytest-cov==7.1.0` |
| Test style | tree mirrors src (`test/unit/<component>/<layer>/.../test_<module>.py`), scoped classes (`TestUserGuest`, `TestUserForSubject`), Triple-A marked with `# arrange / act` / `# assert` comments, behavior-statement method names |
| pre-commit structure | pre-commit-hooks v5.0.0 → ruff (`--fix --exit-non-zero-on-fix`) + ruff-format → local `uv run` hooks (pyright, deptry, bandit, vulture, xenon, import-linter, pytest unit suite) |
| Conventional commits | git log: `feat(filters): ...`, `docs(todo): ...`, `chore(devcontainer): ...` — consistent type(scope): imperative-subject |
| AGENTS.md rules in force | package-by-component; one `VerbNoun` use case with one `execute()`; ports in `application/ports/`; domain services pure (no I/O); "uniform port / use-case surface ... that consistency is the map a newcomer navigates by, not ceremony" |

### 2.4 Structural failure modes measured in reference repos (why not flat)

| Repo | Layout | Cost |
|---|---|---|
| claude-swap | flat `src/claude_swap/*.py` | `switcher.py` 7,431 lines; `autoswitch.py` 2,364; `cli.py` 1,494 — violates the <500-line rule |
| ai-usagebar | mostly flat `src/*.rs` | `config.rs` 4,392 lines; `tui/panels.rs` 2,635; `claude_desktop/mod.rs` 1,606 |
| datastudio `chat` | layered package-by-component | 98 files / 7,536 lines, ~77 lines/file — no god files |

Conclusion driven by the data: component-level nesting with disciplined
layers prevents god files; layer ceremony beyond one level (or layer dirs with
a single member) adds no discoverability. Rules in §4.1 codify the balance.

## 3. Locked decisions (user-confirmed)

| Decision | Choice | Rationale (evidence) |
|---|---|---|
| Stack | Python ≥3.12 + uv; runtime dep `textual` only; stdlib `urllib` for HTTP; stdlib `argparse` for CLI | matches AGENTS.md conventions; claude-swap proves the model in Python; 1 runtime dep = minimal supply-chain surface |
| Credential storage at rest | 0600 files in `$XDG_DATA_HOME/claude-acc-manager` (default `~/.local/share/...`), dirs 0700, atomic tmp+rename writes | claude-swap's proven Linux model; no dbus dependency; Secret Service can be added later behind the storage port |
| Onboarding | login-at-source via `CLAUDE_CONFIG_DIR` | ai-usagebar model; refresh tokens never copied at add time; eliminates the stranded-token failure mode |
| Auto scope | one-shot strategies + `auto --once` tick + foreground `auto` loop; no systemd packaging in v1 | covers manual/scripted/unattended; foreground loop is systemd-runnable by the user without our packaging |
| Account types | OAuth subscription accounts only | usage endpoint rejects API keys (401); strategies require measurable quota; matches "official anthropic claude subscription" requirement |
| `domain/services/` subdir | kept | AGENTS.md named home for pure logic; greppable map |
| CLI layout | single `cli.py`; split into a package only when it crosses 500 lines | measured, not speculative |
| Coverage floor | 95% branch coverage, enforced in the pre-commit hook | user requirement; strictest no-bypass reading |

## 4. Architecture

### 4.1 Structural rules (deterministic; enforced by import-linter where possible)

1. Components are the map; maximum depth `<component>/<layer>/<module>.py`.
2. A layer directory exists only with ≥2 modules; a lone concept becomes a
   named file in its parent (e.g. `shared/fsio.py`, not
   `shared/infrastructure/fsio.py`).
3. One concept per file, file named after the concept — no
   `utils.py`/`helpers.py`/`models.py` grab-bags (greppable-test rule).
4. Split at concept boundaries or the 500-line ceiling, whichever comes first.
   No speculative splits.
5. Ports and use cases keep their named homes even when few
   (`application/ports.py` is the single map of every boundary; one
   `VerbNoun` class with one `execute()` per use-case file).
6. Empty `__init__.py` only — no re-export facades.
7. Test doubles live in `tests/` as named fakes, never in `src/`.
8. Cross-component adapters (`cli.py`, `tui/`) stay top-level and thin; they
   reach components only through use cases and ports.

Import-linter contracts (mechanical enforcement of the above):
`domain` may not import `application`/`infrastructure`; `application` may
import ports + domain only; `infrastructure` may import domain + ports;
`accounts` may import `usage` (never the reverse); `tui`/`cli` import
use cases/ports only.

### 4.2 Component tree (size = realistic estimates; no file near 500)

```
src/claude_acc_manager/                # ~3.8k LOC, 23 files, avg ~165 lines/file
  accounts/                            # the switching domain (~1.5k)
    domain/
      entities.py                      Account, ActiveSlotState
      value_objects.py                 AccountName, SwitchStrategy
      services/
        headroom.py                    pure: 100 − max(5h, 7d, scoped weeklies)
        switch_selection.py            pure: best / next-available / auto ranking — one home
    application/
      ports.py                         AccountStorePort, ActiveSlotPort, ClaudeLockPort,
                                        LoginLauncherPort, ClockPort
      use_cases/
        add_account.py  remove_account.py  list_accounts.py
        switch_account.py  set_account_enabled.py  auto_tick.py
    infrastructure/
      path_resolver.py  file_account_store.py  active_slot.py
      claude_locks.py  login_launcher.py
  usage/                               # measurement domain (~0.9k)
    domain/
      usage_snapshot.py  services/poll_policy.py
    application/
      ports.py                         UsageApiPort, TokenRefresherPort, UsageCachePort
      use_cases/fetch_account_usage.py
    infrastructure/
      anthropic_oauth.py  file_usage_cache.py
  shared/
    fsio.py                            atomic tmp+rename writes, 0600/0700 enforcement
  tui/
    app.py  dashboard.py               textual; splits on growth per rule 4
  cli.py                               argparse dispatch; splits on growth per rule 4
```

### 4.3 Storage layout (all dirs 0700, files 0600, writes atomic)

```
$XDG_DATA_HOME/claude-acc-manager/     # default ~/.local/share/claude-acc-manager
  accounts/<name>/                     ← a real CLAUDE_CONFIG_DIR (login lands here)
    .credentials.json                  ← per-account OAuth blob (mode 0600)
    .claude.json                       ← captured at add time (oauthAccount + metadata)
  registry.json                        account order, active account, enabled flags,
                                       quarantined refresh-token lineages
  usage-cache.json                     last-good usage + 429 backoff state per account
  settings.json                        threshold / interval / cooldown / strategy
  .lock                                flock for our own multi-process operations
```

### 4.4 Token ownership rule (the safety core)

- The **active** account's tokens are refreshed by Claude Code itself — this
  tool never refreshes the active slot (claude-swap's exact policy; refreshing
  it ourselves would race Claude Code's own refresh).
- **Inactive** accounts are refreshed by this tool only when measurement
  requires it (access tokens expire ~hourly); both rotated tokens are
  persisted atomically in one write (one-time-use rule, §2.2).
- At add time tokens are never copied: `add <name>` launches `claude` with
  `CLAUDE_CONFIG_DIR` pointing into the account's own store.

### 4.5 Strategy semantics (claude-swap `switcher.py` `_select_best_switchable`,
`oauth.py account_headroom`, measured behavior)

- `headroom(account) = 100 − max(utilization of binding windows)` where
  binding windows are 5h, 7d, and each active model-scoped weekly.
- `--strategy best`: switch only to an account with **strictly greater**
  headroom than the current one; stay put otherwise; if current headroom is
  unmeasurable, stay (never move on unknowns).
- `--strategy next-available`: rotate in registry order, skipping candidates
  with headroom ≤ 0.
- Disabled accounts and quarantined lineages (`invalid_grant`) are never
  candidates.

### 4.6 Switch transaction (M6; order and rollback per claude-swap evidence)

Under three locks simultaneously: our flock + claude-code's
`.oauth_refresh.lock` + `~/.claude.json.lock` (proper-lockfile-compatible
mkdir locks with staleness, §2.2):

1. Backup the outgoing credential + `oauthAccount` into the outgoing
   account's slot (identity oracle `/api/oauth/profile` classifies an
   unattributable credential before overwriting anything).
2. Read the target account's stored credential + `oauthAccount`.
3. Write target credentials to `~/.claude/.credentials.json` (atomic, 0600).
4. Splice target `oauthAccount` into `~/.claude.json`, preserving all other
   keys (salvage-copy + replace if the file is torn).
5. Update `registry.json`.

Any failure rolls back in reverse. A running Claude Code picks up the new
credentials on its next message.

### 4.7 Auto tick semantics (M9)

- `auto --once`: one check → maybe switch → exit. Exit codes: 0 switched /
  1 error / 2 no action. Scriptable.
- `auto` (loop): default interval 60s (min 15s), threshold 90% (50–99.9),
  cooldown 300s between proactive switches; SIGTERM exits cleanly.
- Proactive switch fires when the active account's binding utilization ≥
  threshold; candidates must be below threshold − hysteresis (10%).
- Quarantined lineages persist across runs (registry).
- Every usage fetch goes through the poll policy (§6) — the loop never
  exceeds the measured 28–30 req/h budget.

## 5. Credential-safety guarantees (each test-enforced)

1. Network egress only to `api.anthropic.com` and `platform.claude.com` —
   allowlist constant in `usage/infrastructure/anthropic_oauth.py` and nowhere
   else; a unit test rejects any other host. No configurable base URLs.
2. No telemetry, no update-check calls home, no third-party endpoints.
3. 0600/0700 + atomic writes everywhere (`shared/fsio.py`, single
   implementation); a unit test asserts modes and rename-atomicity on every
   credential write path.
4. Secrets never in argv, logs, exceptions, or persisted error bodies —
   401/403 bodies are never persisted (they can leak account identifiers;
   ai-usagebar `cache.rs` rule); redaction unit tests assert no token string
   reaches any error surface.
5. Tests are hermetic: no test touches real `$HOME`/`$XDG`/network; paths,
   clocks, and HTTP transports are injected.
6. Refuse to run as root (outside containers).

## 6. Toolchain (mirrors datastudio's proven configuration)

Dev-dependencies (exact pins, locked in `uv.lock`, run via `uv run`):
`pytest==9.1.0`, `pytest-cov==7.1.0`, `ruff`, `pyright`, `bandit`, `radon`,
`xenon`, `vulture`, `deptry`, `import-linter`, `pre-commit`,
`mutmut==3.7.0`. Runtime dep: `textual` (only one; official Textualize
package).

| Tool | Configuration |
|---|---|
| ruff | `target-version py312`, `line-length 100`, select `D,E,W,F,I,B,UP,N`, pydocstyle google, `D` ignored in `test/**`; `I` rules = import sorting, `ruff-format` = formatting (replaces black+isort — no redundant tools) |
| pyright | `typeCheckingMode = "strict"`, `pythonVersion = "3.12"`, venv-aware |
| bandit | `-r src -ll`; exceptions only inline `# nosec Bxxx` with written reason |
| xenon | `--max-absolute B --max-modules B --max-average A` |
| radon | `cc_min A, show_complexity, average` (reporting; xenon gates) |
| vulture | `--min-confidence 80`, paths `src`; whitelist entries each carry a justification comment |
| deptry | verifies imports ↔ pyproject; ignore codes documented in config |
| coverage | branch coverage, source `src/claude_acc_manager`, `fail_under = 95` |
| mutmut | `source_paths = ["src/"]`, tests `test/unit`; every commit gated on zero disqualifying mutants (survived / no tests / suspicious / timeout / segfault / not checked block; killed and `# pragma: no mutate`-skipped allowed) — user-confirmed reversal of the §10 non-goal, added 2026-09-10 |

`.pre-commit-config.yaml` hook order (all gates run on every `git commit`;
~15–20s total):

1. `pre-commit-hooks v5.0.0` — trailing-whitespace, end-of-file-fixer,
   check-yaml, check-toml, check-added-large-files (500kb), check-merge-conflict,
   debug-statements
2. `ruff-pre-commit` (rev pinned to match the dev-dep version) —
   `ruff --fix --exit-non-zero-on-fix`, then `ruff-format`
3. Local hooks (`language: system`, entry `uv run <tool>` so locked versions
   are used, no env drift): pyright → deptry → bandit → vulture → xenon →
   import-linter → `pytest test/unit -q --cov --cov-branch --cov-fail-under=95`
   → mutmut gate (`mutmut run` then fail if `mutmut results` shows any
   disqualifying status; §6 mutmut row)
4. commit-msg stage: conventional-commit regex
   (`feat|fix|test|refactor|chore|docs|build|ci|perf` + optional scope)

**No-bypass policy:** a commit is mechanically impossible unless every gate
passes. No config-level skips; every exception is in-band and auditable
(`# nosec` / `# pragma: no cover` with written justification, reviewed per
milestone). No `--no-verify` in any workflow step.

## 7. Testing protocol

- **TDD strictly**: red (failing test written and observed failing) → green
  (minimal implementation) → refactor. The commit is made at green, one
  logical change per commit (test + implementation together) — this keeps
  every commit hook-passable without bypassing the pytest-in-pre-commit gate.
- **Triple A**, marked in-band with `# arrange / act` / `# assert` comments
  where phases are not self-evident (datastudio style).
- **Scoped test classes** with semantic names: `TestSwitchAccountRollback`,
  `TestHeadroomBindingWindow`, `TestNextAvailableSkipsExhausted`. Method
  names are behavior statements. No loose functions.
- **Named fakes** for all external I/O: `FakeUsageApi`, `FakeTokenRefresher`,
  `InMemoryAccountStore`, `FakeClock`, `FakeLoginLauncher`, tmp-path
  filesystem. No inline stubs.
- Tree mirrors src: `test/unit/<component>/<layer>/test_<module>.py`.
- Hermeticity invariant: no test reads/writes a real `$HOME`/`$XDG` path or
  branches on ambient env; all paths/clocks/transports injected.
- `TERM=dumb` for Textual pilot tests (claude-swap `test_tui.py` proves the
  approach). Subprocess adapter tested with a stub binary; SIGTERM paths via
  injectable handler seam.
- pytest markers: `integration: hits real Anthropic API — run explicitly with
  -m integration` (excluded from default run and the coverage denominator).
- Coverage 95% branch, enforced in the pre-commit hook (§6).
- pytest config: `pythonpath = ["src"]`, `addopts` minimal.

## 8. Commit protocol

Conventional commits, enforced by the commit-msg hook:
`type(scope): imperative subject` — scope = component or concern
(`feat(accounts):`, `fix(usage):`, `test(switch):`, `refactor(fsio):`,
`chore(build):`, `docs(plan):`). One logical change per commit. Each
milestone lands as a series of green commits; nothing is committed red.

## 9. Milestones

Each milestone's exit gate (no exceptions):
`uv run pre-commit run --all-files` clean (includes the mutmut gate) · full
`uv run pytest` green · the milestone's manual validation performed.
Per-commit mutation runtime is measured at each gate; if a full pass exceeds
~2 min, scoping is revisited (`mutmut run "<changed-module>*"` wildcards) —
decided by measurement, not assumption (policy user-confirmed 2026-09-10).

| # | Deliverable | Validation |
|---|---|---|
| M0 | git init; uv scaffold (py312, `textual` runtime pin, dev group with all tools pinned); ruff/pyright/bandit/radon/xenon/vulture/deptry/import-linter/pytest/coverage configs; pre-commit wiring + commit-msg hook; first TDD cycle: `path_resolver` (XDG, `CLAUDE_CONFIG_DIR`, `.claude.json` homedir asymmetry) | all hooks green on `--all-files`; **empirical probe**: run `claude` in a scratch `CLAUDE_CONFIG_DIR`, observe where credentials + config land (keys-only inspection — never print secret values) |
| M1 | `shared/fsio.py` (atomic 0600/0700 writes) + `entities`/`value_objects` + `FileAccountStore` + registry | tests prove modes, rename-atomicity, hermetic tmp-HOME |
| M2 | `active_slot` adapter (read/write credentials, `oauthAccount` splice preserving all other keys, torn-file salvage) + `claude_locks` (proper-lockfile-compatible, staleness) | fixture-file tests; lock interop vs claude-code's mkdir layout |
| M3 | `add` (login-at-source via `LoginLauncherPort`), `remove`, `list`, `status` — no network | hermetic tests incl. fake launcher; manual live `add` against a scratch account |
| M4 | `anthropic_oauth` client: usage GET, token refresh POST, profile GET; injectable transport; endpoint allowlist; token redaction | fake-transport tests (200/401/403/429/`invalid_grant`); redaction tests; allowlist test |
| M5 | `fetch_account_usage` use case (inactive-refresh policy, 429 backoff, last-good cache, cadence + jitter) + `headroom` + `poll_policy` | pure-logic tests + cache-state tests; budget arithmetic test (≤ 30 req/h per identity) |
| M6 | `switch_account` transaction (5 steps + rollback) + `switch_selection` (best / next-available) + manual `switch` CLI | failure-injection at each step asserting rollback; strategy edge cases (strictly-greater, unmeasurable current, all-exhausted) |
| M7 | full CLI (10 commands, `--json` contract, root guard) | command-level tests via isolated HOME; `--json` schema stability test |
| M8 | TUI: dashboard + switch + auto view; reads cache; network only via throttled use case | Textual pilot tests, `TERM=dumb` |
| M9 | `auto_tick` + `auto` loop (`--once` exit codes, threshold/cooldown/hysteresis, quarantine, SIGTERM-clean) | tick-semantics tests; two-account manual dry-run |

Milestone order rationale: strategies (M6) need measurement (M4/M5);
switching (M6) needs the store (M1) and the active-slot adapter (M2);
everything before M4 is network-free and safe to build and validate in
isolation.

## 10. Non-goals (v1, explicit)

macOS/keychain/menubar, Claude Desktop, session-history merging, directory
mappings, aliases, export/import, API-key and setup-token accounts, systemd
unit packaging, Secret Service storage (addable later behind the storage
port). Mutation testing was listed here originally but was promoted to a
per-commit gate on 2026-09-10 (user decision; see §6 mutmut row) — it is the
standard mitigation for the §11 "95% coverage pressure creating weak tests"
risk.

## 11. Risks and mitigations

| Risk | Evidence | Mitigation |
|---|---|---|
| `/api/oauth/usage` is undocumented and can change | claudeops-tui caveats; open feature requests anthropics/claude-code#44328, #32796 asking for an official surface | schema-tolerant parsing (missing window → `None`, not crash, per shunt/ai-usagebar practice); `integration`-marked smoke test to re-verify shape; unknown-field drift surfaced, not swallowed |
| Usage endpoint 429 wall | #31637, #30930; claude-swap's measured 28–30 req/h budget | poll policy constants from claude-swap's measurements; last-good cache + persisted backoff; 429 treated as throttle (trust last-good until window reset), never as account exhaustion |
| `User-Agent` requirement changes | #31021 workaround could be tightened by Anthropic | UA pinned to a real claude-code version constant; single point of change |
| Refresh-token stranding | one-time-use rotation (#31021, #30930) | single atomic write of both rotated tokens; failed persist = hard failure with re-login guidance (ai-usagebar's rule); login-at-source at add time |
| Switch corrupts a live session | claude-swap's lock interop (§2.2) | reimplement proper-lockfile mkdir locks with staleness; transaction + rollback; M2 interop tests |
| 95% coverage pressure creating weak tests | — | coverage is the floor, not the goal: named fakes + pilot tests; `# pragma: no cover` requires written justification reviewed at each milestone gate |
| `CLAUDE_CONFIG_DIR` layout differs on this claude-code version | claude-swap `paths.py` behavior vs unverified 2.1.267 | M0 empirical probe before any code depends on it |
