# SL-009 — `cam auto`: unattended threshold-driven account switching

Milestone: M9 · State: open · Depends on: SL-006 (switch transaction) | SL-008 (TUI preview) · Closes: GAP-004 | GAP-007

> Ephemeral PRD — delete when M9 ships. Every `research_repos/` path below was verified with `test -e` on 2026-10-02.

## Outcome

A user can run `cam auto` (foreground loop) or `cam auto --once` (cron/systemd-timer friendly) to have `cam` switch the live Claude login to a healthier registered account when the active one nears its rate limit — with persisted policy (`settings.json` + `cam config`), cooldown/hysteresis/recovery anti-flap guards, quarantine persistence, and a SIGTERM-clean exit.

## Exit gate

`uv run pre-commit run --all-files` clean · full `uv run pytest` green (≥95% branch) · mutmut 0 survivors · then the manual validation below on an isolated `HOME`/`XDG_DATA_HOME` with two accounts seeded through the real `FileAccountStore`/`FileUsageCache` (same harness as M8). Measurements go in the closing commit's body.

1. Both accounts' cached usage below threshold → `cam auto --once` exits `2` and prints a no-switch line.
2. Active account over threshold, one healthy candidate → `cam auto --once` exits `0` and `cam status` confirms the target is live.
3. Re-seed so the new active is *also* past the threshold but above 0 headroom → immediate second `cam auto --once` exits `2` (cooldown holds proactive moves).
4. Seed active at/over the limit (headroom ≤ 0) → `cam auto --once` exits `0` despite the cooldown (at-limit escape).
5. All accounts at/over the limit with a known reset → `cam auto --once` exits `3`; `cam auto` loop sleeps toward the earliest reset (bounded).
6. `cam auto --dry-run --once` reports the would-be switch; `registry.json`, `auto-state.json`, and the live slot are untouched.
7. `cam config set autoswitch.threshold 80` then `cam auto --once` honors 80; `cam config get/list/unset/path` behave per spec; `cam config set` out-of-range/garbage exits `1` loudly.
8. Poll-plan compliance: a candidate seeded with a future `next_poll_at_s` and an expired parked token is NOT fetched (no `last_error` written); the same entry flipped due IS fetched (transport error recorded) — proven offline, no network.
9. `cam auto` running: `kill -TERM` exits `0` promptly; `Ctrl-C` exits `130`.
10. `cam auto --json --once` emits one JSON event object per line on stdout; exit code still carries the outcome.

## Who else implements this

| Repo | Has it | Entry points | Approach in one line |
| --- | --- | --- | --- |
| claude-swap | FULL | `research_repos/claude-swap/src/claude_swap/autoswitch.py`, `settings.py`, `poll_policy.py`, `usage_store.py`, `switcher.py`, `cli.py` | UI-agnostic `AutoSwitchEngine` emitting typed events; `autoswitch_state.json` (cooldown/quarantine/no-return snapshot) under a dedicated lock; two-phase scheduled usage collection; flag-overridable `settings.json` + `config` subcommands |
| ai-usagebar | ABSENT | `research_repos/ai-usagebar/src/account.rs` (manual `account switch` only), `config.rs`, `cache.rs` | No loop/engine — manual switch + TOML settings overlay; contributes atomic-write and path-resolver evidence only |
| claude-code itself (vendor behavior we must interoperate with) | — | usage endpoint budget (~28–30 req/h/identity rolling-hour, `Retry-After`), `.credentials.json` schema, mkdir locks | No multi-account concept; imposes the rate budget every fetch must respect and the file shapes/locks we already interoperate with |

**Count:** 1 of the references implements this. The capability is real but has exactly one implementation to study — the port stays scoped to our milestone contract rather than absorbing the reference's accumulated edge-cases wholesale (its engine is 2364 lines with failover/idle-hold/consume-first/live-session/model-scoped axes we defer).

## Implementation inventory

### claude-swap

| Concern | Files |
| --- | --- |
| Domain logic (triggers, ranking, cooldown, no-return, recovery axis, constants) | `research_repos/claude-swap/src/claude_swap/autoswitch.py` (constants + `TickOutcome` ~L100-280; `_tick_inner` ~L892-1382; `_no_return_account`/`_left_account_recovered`/`_rank_candidates` ~L1384-1951; `_earliest_recovery` ~L2226-2260) |
| Ports / boundaries (collector contract, poll-inputs pin, quarantine/state surface) | `research_repos/claude-swap/src/claude_swap/switcher.py` (`usage_entries_by_account` + `_collect_usage_entries` ~L1721-1774, 4960-5077; `set_poll_policy_inputs`/`clear_poll_policy_inputs`/`_poll_policy_inputs` ~L1792-1823; `switchable_account_numbers` ~L1825-1839) |
| Use case / orchestration (tick, loop, delays, freshen, perform) | `research_repos/claude-swap/src/claude_swap/autoswitch.py` (`tick`/`_collect_scheduled_usage` ~L879-2097; `_freshen_target`/`_note_token_identity` ~L769-875; `_perform` ~L2099-2172; `_next_delay`/`_respect_poll_plan`/`run_loop`/`stop`/`wake`/`apply_threshold` ~L2267-2364) |
| Infrastructure adapter (state file, atomic JSON, locks) | `research_repos/claude-swap/src/claude_swap/autoswitch.py` (`_state_lock`/`_read_state`/`_mutate_state`/`_quarantine`/`_release_recovered_quarantines` ~L690-765); `research_repos/claude-swap/src/claude_swap/settings.py` (`atomic_write_json` ~L443-488) |
| CLI / TUI entry point | `research_repos/claude-swap/src/claude_swap/cli.py` (`_auto_command` ~L576-745: pre-dispatch, flags, SIGTERM→`engine.stop()`, exit `engine.tick().value`; `_config_command` ~L748+: `config list|get KEY|set KEY VALUE|unset KEY|path`) |
| Persistence | `research_repos/claude-swap/src/claude_swap/settings.py` (whole file: `AutoSwitchSettings`, `SETTING_SPECS`, forgiving `_clamped` load, strict `parse_setting_value`, `set_setting`/`unset_setting`/`effective_settings`/`merged_with_cli`); `autoswitch_state.json` schema in `autoswitch.py` (`schemaVersion`, `lastSwitchAt`, `lastSwitchTo`, `lastSwitchFrom`, `leftHeadroom`, `leftRecoveryAt`, `leftTrigger`, `quarantine{}`) |
| Poll cadence + escalation + due-candidate scheduling | `research_repos/claude-swap/src/claude_swap/poll_policy.py` (whole file: `URGENT_INTERVAL_S`, `ESCALATION_MARGIN_PCT`, `plan_after_fetch` urgent branch); `research_repos/claude-swap/src/claude_swap/usage_store.py` (`due_candidate` ~L431-472, `plan_oversleeps_interval`/`_plan_oversleeps_interval` ~L405-428) |
| Error / edge cases | `research_repos/claude-swap/src/claude_swap/autoswitch.py` (outcome mapping throughout `_tick_inner`; `TickOutcome.BLOCKED`; `_SYSTEMIC_STATUSES`/`_SYSTEMIC_MESSAGES`); `research_repos/claude-swap/tests/test_autoswitch.py` (6896 lines, 252 tests — tick semantics reference), `tests/test_settings.py` |

### ai-usagebar (absence evidence + reuse candidates)

| Concern | Files |
| --- | --- |
| Persistence (atomic cache writes, path resolvers) | `research_repos/ai-usagebar/src/cache.rs` |
| Settings surface (TOML config + overlay edit) | `research_repos/ai-usagebar/src/config.rs` |
| Manual-only account switching (absence proof) | `research_repos/ai-usagebar/src/account.rs` |

## Trade-offs and what we adopt

| Axis | Options seen (repo → approach) | Trade-off | Our choice, and why |
| ---- | ------------------------------ | --------- | ------------------- |
| `--once` exit codes | ADR-0006 → `0/1/2`; claude-swap → `0/1/2` + `3=BLOCKED`; monitoring-plugin convention (Nagios) → a middle "attention, not error" tier | Folding "wanted to switch but no viable target / fleet exhausted" into `2` hides the one outcome a wrapper most needs to page on; a distinct code costs one enum member | **Adopt `3=BLOCKED`**; amend ADR-0006 in place at ship (it predates the engine design; the reference added `3` deliberately for exactly this contract) |
| Quarantine persistence | claude-swap → `quarantine{}` map inside `autoswitch_state.json`; ours → `registry.json` tombstones (ADR-0009, fingerprint-bound, auto-release on re-login) already wired into `switch_selection`, `cam list`, TUI | A second quarantine store duplicates the fingerprint-release machinery and can disagree with the one `cam list` shows | **Reuse `registry.json`** via `QuarantineDeadLineage`; `auto-state.json` carries cooldown + no-return snapshot only (no `quarantine` map) |
| Settings write surface | claude-swap → `config list|get|set|unset|path` with strict validation; ai-usagebar → TOML overlay edit; industry peers (git/npm/gh/aws) → `config get/set` | A persisted file with no validated write path makes hand-edited typos silently degrade through the forgiving loader | **Ship `cam config`** scoped to `autoswitch.*`: `threshold`, `intervalSeconds`, `cooldownSeconds`, `hysteresisPct`, `strategy` |
| Settings load vs write discipline | claude-swap → forgiving clamp on read, strict `ConfigError` on `set`; corrupt file = defaults on read, `ConfigError` on write | One discipline for both either silently eats typos (lenient set) or bricks `cam auto` on a bad hand edit (strict read) | **Port both disciplines** — `_read_raw` forgiving, `_read_raw_for_write` strict (same split as `settings.py`) |
| Settings `strategy` domain | claude-swap → `best`/`consume-first`; ours → `switch_selection.py` has `best`/`next-available`/`rotation` | `consume-first` needs weekly-reset-ordered ranking + two-phase commit — a different objective the reference added later | **`best` (default) + `next-available`**; `consume-first` and `rotation` stay out of the auto settings domain |
| Engine ↔ use cases | AGENTS.md → a use case never depends on another use case; the engine must call the real `SwitchAccount` transaction and `FetchAccountUsage` collector | Duplicating the transaction is a non-starter; concrete use-case injection breaks the layering rule | **New ports in the capability's home component**: `SwitchExecutorPort` (accounts, implemented by `SwitchAccount`), `UsageFetchPort` (usage, implemented by `FetchAccountUsage`), `LineageQuarantinePort` (accounts, implemented by `QuarantineDeadLineage`) — consumed by the engine |
| Anti-flap depth | contract (threshold/cooldown/hysteresis) only; + all-exhausted park; + recovery-axis ranking + no-return bar (reference's measured fix for `[1,2,1,2]` ping-pong); full engine (failover, idle-hold, consume-first, live-session, api-key, model axes) | Parking when everything is exhausted strands the user on a hard-limited account while a peer resets in minutes — the recovery axis is why the reference stopped parking; but it can flap without the no-return memory | **Contract + recovery axis + simplified no-return** (bar the account we left until it demonstrably recovers); failover/idle-hold/consume-first/api-key/model/live-session deferred |
| Nominated-fetch semantics | ours today → `poll_due` gate is absolute inside `FetchAccountUsage`; claude-swap → engine-nominated `fetch=` sets bypass serve-TTL/plan (never backoff) so urgent plans and escalation actually fetch | Without an override, a 60s urgent plan can never beat the 180s serve TTL and escalation cannot freshen a non-due candidate | **`force: bool` on `execute()`** — skips the serve-TTL early return and the not-due hold, never the backoff; engine nominates only due/never-fetched/stale-plan/escalated accounts |
| Threshold into poll planning | ours today → none (threshold-independent core, M5 port); claude-swap → `set_poll_policy_inputs` pin + settings-file fallback (`_poll_policy_inputs`) | Urgent mode needs *a* threshold; every surface should plan against the same value, including CLI overrides mid-session | **`threshold: float | None` on `execute()`** + injected `SettingsPort` fallback — `cam auto` pins its merged threshold per call, other surfaces follow `settings.json` |
| Loop sleep | fixed `interval_seconds`; claude-swap → `_next_delay` jitter ±10% + `_respect_poll_plan` (shorten to active's `next_poll_at`, floored at `URGENT_INTERVAL_S`) + blocked sleeps (`sleep-until` earliest reset +slack capped at `MAX_SLEEP_S`, else `max(interval, 300)`) | A fixed loop either lags the urgent plan or ignores the budget the planner encoded | **Port plan-aware delay** — shorten-only, never below the planner's floor |
| State locking | reuse the store's single `.lock` (FileUsageCache discipline) vs claude-swap's dedicated `.autoswitch_state.lock` | The decide→switch→record hold spans `SwitchAccount`, whose registry writes take `.lock` — reusing it self-deadlocks | **Dedicated `.auto-state.lock`** |
| Event transport under `--json` | ours → one `dict` returned, `dispatch` owns `json.dumps`; claude-swap → JSONL, one event object per line | A tick/loop emits *many* events; one dict can't stream them | **JSONL inside `cmd_auto`** — deviation from the single-dict convention, documented here |

## Gap analysis — what we already have vs the references

| Concern | Ours today (file) | Best reference (file) | Gap |
| ------- | ----------------- | --------------------- | --- |
| Threshold/at-limit trigger + cooldown + candidate hysteresis | absent | `autoswitch.py` `_tick_inner`/`_rank_candidates`/`_in_cooldown` | absent — build `auto` component |
| Foreground loop (jitter, plan-aware delay, blocked sleeps, stop event) | absent | `autoswitch.py` `run_loop`/`_next_delay`/`_respect_poll_plan` | absent — build |
| Typed tick events (`poll`/`switch`/`no-switch`/`quarantined`/`all-exhausted`/`sleep`/`error`) | absent | `autoswitch.py` `AutoSwitchEvent` hierarchy ~L281-497 | absent — build |
| Cooldown + no-return departure snapshot (`lastSwitchAt`/`lastSwitchFrom`/`leftHeadroom`/`leftRecoveryAt`) | absent — no engine state file | `autoswitch.py` `_perform`/`_read_state`/`_mutate_state` | absent — `auto-state.json` + `AutoStatePort` |
| Candidate freshen before activate (expired parked token → refresh; `invalid_grant` → quarantine) | partial — `FetchAccountUsage._resolve_access_token` refreshes expired *inactive* tokens during polls; nothing forces it pre-switch | `autoswitch.py` `_freshen_target` | partial — new `FreshenTarget` use case reusing `TokenRefresherPort`/`CredentialStorePort`; no identity-conflict axis (we don't parse token-account identity) |
| Quarantine on dead lineage | **present and complete** — `QuarantineDeadLineage`, registry tombstones, fingerprint release; used by `switch_selection`, `cam list`, TUI | `autoswitch.py` `_quarantine`/`_release_recovered_quarantines` | complete — reuse as-is (GAP-004's "quarantine persistence" = engine must *use* it) |
| Scheduled collection: active-due check, one due candidate, escalation near threshold | absent — `FetchAccountUsage` fetches one named account per call | `autoswitch.py` `_collect_scheduled_usage`; `usage_store.py` `due_candidate`/`plan_oversleeps_interval` | absent — engine-side orchestration + two pure fns in `poll_policy.py` |
| Urgent-mode cadence (`URGENT_INTERVAL_S`, `ESCALATION_MARGIN_PCT`, threshold input) | partial — movement/backoff/reset-clamp machinery exists; no threshold input or urgent branch | `poll_policy.py` `plan_after_fetch` | partial — add constants + `threshold` param + urgent branch; thread threshold through `FetchAccountUsage` |
| Poll-plan-aware fetch override for nominated accounts | absent — `poll_due` gate absolute | `switcher.py` `_collect_usage_entries` `fetch=`/`scheduled=`; `usage_store.py` `reserve` | partial — `force` flag on `execute()` (never bypasses backoff) |
| `settings.json` (schema, forgiving load, atomic private write) | absent | `settings.py` (whole file) | absent — `settings` component |
| `cam config` settings surface | absent | `cli.py` `_config_command` + `settings.py` `set_setting`/`unset_setting`/`effective_settings`/`setting_spec`/`parse_setting_value` | absent — `cam config` subcommand (GAP-007) |
| `cam auto` command (`--once`/flags/`--dry-run`/`--json`, SIGTERM) | absent | `cli.py` `_auto_command` | absent — `cmd_auto` |
| Switch transaction incl. dry-run | **present and complete** — `SwitchAccount` (locks, rollback, `--dry-run`, `headroom=` input) | `switcher.py` `switch_to` | complete — expose via `SwitchExecutorPort` |
| Unmanaged-active / no-active refusal | **present** — `SwitchAccount`/`StatusAccount` live-resolved identity | `autoswitch.py` `_tick_inner` ~L908-929 | present — engine re-checks via slot+store ports |
| TUI auto screen | present as **dry-run preview** (`tui/autoview.py`); engine hosting deferred | `autoswitch.py` `apply_threshold`/`wake`; TUI auto view | out of scope this milestone (see below) |

## Deviations

- **Quarantine lives in `registry.json`, not the state file.** claude-swap's `autoswitch_state.json.quarantine` exists because its registry has no lineage tombstones; ours does (ADR-0009). `auto-state.json` carries `schemaVersion`, `lastSwitchAt`, `lastSwitchFrom`, `leftHeadroom`, `leftRecoveryAt` only.
- **No failover trigger.** `unhealthy_ticks`/`active-usage-unknown`→`failover` handling is deferred: an unreadable active yields `NO_ACTION` (reason `active-usage-unknown`) and normal cadence. Without failover the reference's `IDLE_HOLD`/`USAGE_TOKEN_EXPIRED` machinery is unnecessary and is not ported.
- **No `consume-first`, no `includeApiKeyAccounts`, no `model`, no live-session skip, no identity-conflict check.** `strategy` ∈ `{best, next-available}`; API-key accounts don't exist here (ADR-0005); `cam run`-style scoped sessions don't exist; we don't parse token-account identity on refresh.
- **`--once` gains exit `3` (BLOCKED)** — amends ADR-0006 (it documented 0/1/2 before the engine design existed).
- **State file named `auto-state.json`, lock `.auto-state.lock`** (store's `.lock` would self-deadlock across the switch hold).
- **`cam auto --json` emits JSONL** (one event per line), not a single dict — the dispatch single-dict convention stays for every other command.
- **No `wake()`/`apply_threshold`/`set_poll_policy_inputs`-style mutable pin** — those exist for the hosted-engine TUI path, deferred with it.
- **Simplified no-return guard** (bar last-switch-from until it recovers by `+SPENT_HEADROOM_PCT` over the departure baseline, or crosses the landing floor, or its binding reset improves by `RECOVERY_HYSTERESIS_S`) instead of the reference's full `_left_account_recovered` five-branch matrix (its failover/consume-first legs belong to deferred axes). If the simplified guard proves insufficient, the full port is a follow-up — the state fields needed (`leftHeadroom`/`leftRecoveryAt`) are written from day one.

## Open decisions

- **`--once` in `BLOCKED`: print the would-be sleep?** Reference emits `AllExhaustedEvent` with `earliest_reset_at`. Adopt: emit the event; loop uses it for `_sleep_until`; `--once` prints it on the no-switch line. (Resolves during T9 — flag if the event shape fights the renderer.)
- **`next-available` as an auto `strategy`.** Our selector supports it; reference's auto doesn't (it predates the setting or considers it a manual-only strategy). Included as a choice because the settings domain must accept what the engine honors — revisit only if a test shows it can't compose with the recovery axis (it can: all-exhausted overrides strategy by design in the reference).
- **Concurrency claims.** The reference's `UsageStore.reserve` claims a fetch slot so two processes can't double-fetch. Ours has no claim mechanism anywhere (accepted since M7) — the auto-state lock serializes the *decision*, fetch races stay as-is. Note in code comment; revisit only if observed.

## Surface

| Layer | Files |
| ----- | ----- |
| domain | `settings/domain/settings_spec.py` (`AutoSettings`, `SETTING_SPECS`, clamp/parse — pure); `auto/domain/auto_event.py` (`AutoEvent` hierarchy + `TickOutcome`); `auto/domain/services/auto_rank.py` (trigger classification, eligibility, headroom/recovery ranking, hysteresis/cooldown predicates, simplified no-return, `earliest_recovery_s`); `auto/domain/services/loop_delay.py` (`next_delay`, `respect_poll_plan`); `usage/domain/services/poll_policy.py` (+`URGENT_INTERVAL_S`, `ESCALATION_MARGIN_PCT`, `threshold`, `due_candidate`, `plan_oversleeps_interval`) |
| application (ports / use cases) | `settings/application/ports.py` (`SettingsPort`); `settings/application/use_cases/{load,save}_settings.py`, `{set,unset,list}_setting.py` (or equivalent split); `auto/application/ports.py` (`AutoStatePort`); `auto/application/auto_engine.py` (`AutoEngine`: `tick`, `run_loop`, `stop`); `auto/application/use_cases/freshen_target.py`; `accounts/application/ports.py` (+`SwitchExecutorPort`, `LineageQuarantinePort`); `usage/application/ports.py` (+`UsageFetchPort`); `switch_account.py`/`quarantine_dead_lineage.py`/`fetch_account_usage.py` (declare the ports) |
| infrastructure | `settings/infrastructure/file_settings.py` (`settings.json`, shared `.lock`, `fsio`); `auto/infrastructure/file_auto_state.py` (`auto-state.json`, `.auto-state.lock`) |
| cli / tui | `cli/parser.py` (`auto`, `config` subcommands), `cli/commands.py` (`cmd_auto`, `cmd_config` incl. SIGTERM wiring), `cli/context.py` (new use cases + engine factory), `cli/json_output.py` (config payload + event JSONL shape), `__main__.py` (wiring); TUI untouched |
| tests | `test/unit/settings/` (spec, file adapter, config command), `test/unit/auto/` (rank, delay, state, freshen, engine tick/loop, `cmd_auto`), `test/support/` fakes (`in_memory_settings.py`, `in_memory_auto_state.py`), `test/unit/test_cli.py` additions |

## Tasks

One TDD unit each, one conventional commit each.

- [x] T1 — `settings/domain/settings_spec.py`: `AutoSettings` dataclass, `SETTING_SPECS` for `autoswitch.{threshold,intervalSeconds,cooldownSeconds,hysteresisPct,strategy}`, forgiving clamp + strict `parse_setting_value`. `test(unit)`: defaults, clamped loads, strict set errors.
- [x] T2 — `SettingsPort` + `FileSettings` adapter (forgiving `_read_raw`, strict write-path read, atomic 0600, preserves unknown keys) + `LoadSettings`/`SetSetting`/`UnsetSetting`/`ListSettings` use cases.
- [x] T3 — `cam config` subcommand: `get|set|unset|list|path`, `--json` payload, error text via dispatch. Parser + `cmd_config` + wiring.
- [x] T4 — urgent-mode poll policy: `URGENT_INTERVAL_S`/`ESCALATION_MARGIN_PCT`/`threshold` param + urgent branch in `plan_after_fetch`; `FetchAccountUsage.execute(force, threshold)` + injected `SettingsPort`; `UsageFetchPort` declared.
- [x] T5 — `poll_policy.due_candidate` + `plan_oversleeps_interval` (pure, over `UsageCacheEntry` fields) with stalest-first ordering, backoff exclusion, overslept-plan detection.
- [x] T6 — `AutoStatePort` + `FileAutoState`: `auto-state.json` (schema v1, fields above), mutate-under-`.auto-state.lock`, torn-file → loud `ValueError` (§11 discipline).
- [x] T7 — `FreshenTarget` use case: parked credential near/at expiry → `TokenRefresherPort.refresh` → `persist_rotation`; `invalid_grant` → "dead" (caller quarantines); transport → "transient"; unexpired → "ok".
- [x] T8 — `auto_rank` domain service: trigger classify (below/proactive/at-limit), candidate eligibility (enabled/quarantined/credentials/registry-order), headroom-axis ranking with hysteresis, all-exhausted recovery axis + `RECOVERY_HYSTERESIS_S`, simplified no-return guard, `in_cooldown`, `earliest_recovery_s`.
- [x] T9 — `AutoEngine.tick()`: live-resolve active → refuse unmanaged/none → scheduled collect (active due/stale-plan/overslept + one due candidate + escalate near band/unknown) → trigger → cooldown (state) → rank (no-return) → per-candidate `FreshenTarget` → `invalid_grant`→quarantine/`transient`→skip → state-locked recheck→`SwitchExecutorPort`→record (`lastSwitchAt`/`lastSwitchFrom`/`leftHeadroom`/`leftRecoveryAt`) → emit events → `TickOutcome`. Never raises.
- [x] T10 — `loop_delay` domain (`next_delay` jitter/blocked/sleep-until, `respect_poll_plan` shorten-only) + `AutoEngine.run_loop`/`stop` (threading.Event; stop-before-start exits immediately; SIGTERM handler lands in `cmd_auto`).
- [ ] T11 — `cam auto`: parser flags (`--once --interval --threshold --cooldown --strategy --dry-run --json`), `cmd_auto` (settings load + `merged_with_cli`-style overlay, human/JSONL emitters, `sys.exit(tick().value)` vs loop), `UseCases`/`__main__` wiring, `SwitchExecutorPort`/`LineageQuarantinePort` declarations on existing use cases.
- [ ] T12 — ship: exit gate, manual validation (above), backlog M9→`shipped`, parity matrix GAP-004/GAP-007 rows, ADR-0006 amendment (exit 3), delete this PRD.

## Out of scope

- TUI-hosted engine (`apply_threshold`/`wake`/live event log on `AutoScreen`) — next slice; the M8 preview stays as-is.
- Failover-after-N-unhealthy-ticks and the `IDLE_HOLD`/`USAGE_TOKEN_EXPIRED` machinery (its only consumer) — needs evidence the unreadable-active case matters here.
- `consume-first` strategy (weekly-reset-ordered proactive moves + two-phase commit).
- Model-scoped weekly windows (`autoswitch.model`, `cam switch --model` persistence) — the flag stays accepted-but-dormant as today.
- API-key accounts (ADR-0005), `cam run` scoped sessions (no session launcher exists), live-session detection.
- Identity-conflict check on freshen (requires parsing `account` from the refresh response — not in our wire model).
- Multi-process fetch *claims* (`UsageStore.reserve` semantics) — fetch races accepted as today; the state lock serializes decisions.
- systemd unit packaging (ADR-0006), macOS keychain, desktop integration, session merging, directory mappings, aliases, export/import.
- `extra_usage` parsing (ADR-0012 — no consumer).
