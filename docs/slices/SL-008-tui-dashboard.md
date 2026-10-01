# SL-008 — TUI: dashboard, switch, watch, auto preview

Milestone: M8 · State: in-progress · Depends on: SL-007 (shipped) · Closes: GAP-005

## Outcome

A user can run `cam tui` (or `cam watch`) to watch every managed account's quota live — the active account full-size, the others as one-line minis — switch with a keypress, toggle enable/disable, remove an account behind a confirm, and see what a `best`-strategy auto-switch would do, all without leaving the terminal; every fetch the TUI triggers respects the persisted per-account poll plan.

## Exit gate

`uv run pre-commit run --all-files` clean · full `uv run pytest` green · then the manual validation below, run by a human or scripted against the real tool. Measurements go in the closing commit's body.

1. On an isolated `HOME` + `XDG_DATA_HOME` with two seeded accounts: `cam tui` renders the active account's full card and the other's mini line; `cam watch` opens directly on the watch screen.
2. `s` opens the switch screen, Enter on the other account switches — `cam status` confirms the live slot moved; `b` picks the `best` strategy.
3. With the TUI open past `SERVE_TTL_S`, `usage-cache.json` `fetched_at_s` values advance no faster than the persisted `next_poll_at_s` plans — the poller cannot storm the endpoint.
4. `TERM=dumb` runs the Pilot suite green; a real `TERM=dumb cam tui` launch degrades without a crash.

Write this PRD to be grepped: do not hard-wrap paragraphs, keep one fact per table row, write file names in full, and tag every gap it closes with its `GAP-NNN`.

## Who else implements this

| Repo | Has it | Entry points | Approach in one line |
| --- | --- | --- | --- |
| claude-swap | FULL | `research_repos/claude-swap/src/claude_swap/tui/` (`app.py`, `dashboard.py`, `autoview.py`, `widgets.py`, `modals.py`, `data.py`, `theme.py`, `cswap.tcss`), `research_repos/claude-swap/src/claude_swap/snapshot_source.py`, `research_repos/claude-swap/tests/test_tui.py` | One `App` owns a 3s poll loop driving `SnapshotSource` → `switcher.accounts_snapshot(fetch=None)` (the store's `reserve` decides who may fetch); blocking actions run captured in thread workers; screens = dashboard menu + shared `AccountListScreen` (switch, watch) + engine-hosted auto view. |
| ai-usagebar | PARTIAL | `research_repos/ai-usagebar/src/tui/` (`app.rs`, `panels.rs`, `view.rs`, `settings.rs`), `research_repos/ai-usagebar/src/account.rs` | ratatui vendor-usage panels with severity gauges + a settings overlay — a different surface: no Claude account switching (that stays CLI-only in `account.rs`), so its TUI is a render reference, not a behavior one. |
| claude-code itself | — | — | No interop surface this milestone — the TUI touches no claude-owned file beyond what M2 (`active_slot`, `claude_locks`) and M6 (switch transaction) already own. |

**Count:** 1 of 2 implementable references has it in full; ai-usagebar's TUI is a different capability. The port target is claude-swap's `tui/` minus the parts tied to non-goals (token add, API-key sentinels, spend row) or to M9 (engine, persisted settings, store-only lane).

## Implementation inventory

### claude-swap

| Concern | Files |
| --- | --- |
| Entry point (`tui`/`watch`, lazy imports) | `research_repos/claude-swap/src/claude_swap/tui/__init__.py` — `run(switcher, start)` imports textual inside `run`, probes the terminal background in cooked mode, drains stdin; dispatch at `research_repos/claude-swap/src/claude_swap/cli.py` ~L1442 (`--tui`/`--watch`, bare `cswap` on a tty) |
| App + poll loop + action workers | `research_repos/claude-swap/src/claude_swap/tui/app.py` — `CswapApp` reactives (`snapshot`, `refresh_status`, `busy`), `POLL_INTERVAL_S`/`SNAPSHOT_AGE_NOTE_S`, two refresh lanes (normal + store-only), generation guard, `on_worker_state_changed`, `_start_action`/`run_action` |
| Snapshot source / fetch pacing | `research_repos/claude-swap/src/claude_swap/snapshot_source.py` — `take(full, store_only)`, `_reconcile` (late-worker fetched_at regression guard, token-expired sentinel stickiness), `account_identity` |
| Store-governed eligibility | `research_repos/claude-swap/src/claude_swap/usage_store.py` — `reserve` (~L993: stale ∧ poll-due ∧ ¬backoff ∧ ¬quarantined ∧ ¬claimed, fenced claim lease), `UsageEntry` (~L273), `STALE_OK_S`, `SERVE_TTL_S`; collect pass at `research_repos/claude-swap/src/claude_swap/switcher.py` `_collect_usage_entries` (~L4949), `accounts_snapshot` (~L1736) |
| Dashboard + menus | `research_repos/claude-swap/src/claude_swap/tui/dashboard.py` — `DashboardScreen` (nested `MenuItem` stack), `AccountListScreen` (rebuild-on-numbers-change, cursor restore, fetched_at flash), `SwitchScreen`, `WatchScreen` (armable selection) |
| Auto view | `research_repos/claude-swap/src/claude_swap/tui/autoview.py` — `AutoScreen` (DRY-RUN default, threshold session-adjust, "Next best" ranking via `binding_pct`, `RichLog` event feed from `AutoSwitchEngine`) — engine itself is `research_repos/claude-swap/src/claude_swap/autoswitch.py` (M9 for us) |
| Widgets / renderers | `research_repos/claude-swap/src/claude_swap/tui/widgets.py` — `bar_cells`, `usage_bar`, `usage_rows`, `account_card_text`, `mini_account_text`, `AccountsPanel`, `AccountCard`, `AccountItem`, `MenuItem` |
| Modals | `research_repos/claude-swap/src/claude_swap/tui/modals.py` — `ConfirmModal`, `AddTokenModal` (setup-token/API-key — non-goal for us), `OutputModal` (captured ANSI output — ours returns typed results) |
| Display helpers | `research_repos/claude-swap/src/claude_swap/tui/data.py` — `format_duration`, `format_age`, `reset_text`, `reset_clock`, `clock_stamp`, `window_pct`, `window_reset_text`, `sentinel_label` |
| Theme | `research_repos/claude-swap/src/claude_swap/tui/theme.py` (`Palette`, `CSWAP_DARK`, `CSWAP_LIGHT`, severity ramp WARN 70 / CRIT 90) + `research_repos/claude-swap/src/claude_swap/tui/cswap.tcss`; background detection in `research_repos/claude-swap/src/claude_swap/appearance.py` (OSC 11 + DA1, cooked-mode-only) |
| Pace marker | `research_repos/claude-swap/src/claude_swap/pace.py` — `compute_pace` (weekly windows only, `WEEKLY_PERIOD_S`, `SUPPRESS_AFTER_RESET_S` 24h, `AHEAD_THRESHOLD_PCT` 15pp) |
| Settings the TUI reads | `research_repos/claude-swap/src/claude_swap/settings.py` — `load_settings` (threshold/interval), `load_ui_settings` (theme), `set_setting`, `SETTING_SPECS` — all M9 for us (GAP-007) |
| Test harness | `research_repos/claude-swap/tests/test_tui.py` — `FakeSwitcher`, `app.run_test(size=…)` Pilot tests, `settle()`/`menu_select()` helpers, sync unit tests for helpers/renderers; pytest-asyncio markers |

### ai-usagebar

| Concern | Files |
| --- | --- |
| Usage panel renderers | `research_repos/ai-usagebar/src/tui/panels.rs` — ratatui `Section`s (gauge + footnote), severity colors, reset metadata per row |
| TUI shell + settings overlay | `research_repos/ai-usagebar/src/tui/app.rs`, `research_repos/ai-usagebar/src/tui/view.rs`, `research_repos/ai-usagebar/src/tui/settings.rs` — toml-backed settings editing; ours defers settings to M9 |

## Trade-offs and what we adopt

| Axis | Options seen (repo → approach) | Trade-off | Our choice, and why |
| ---- | ---------------------------- | --------- | ------------------- |
| Fetch eligibility for a poller | claude-swap → `reserve` atomic gate (stale ∧ poll-due ∧ ¬backoff ∧ ¬quarantined ∧ ¬claimed, fenced lease); ours today → `FetchAccountUsage` checks `is_fresh` only | Ungated 3s polling refetches every account past the serve TTL and keeps hitting a 429'd endpoint; the persisted `next_poll_at_s` plan is currently write-only (grep: only storage/tests read it) | Adopt the gate inside `FetchAccountUsage.execute` for all callers — the reference's on-demand semantics (`respect_plans=True`): stale ∧ `poll_due` ∧ ¬`in_backoff`. Quarantine exclusion stays caller-side (the registry lives in `accounts`; `usage` can't see it). Claim fencing is not ported — single-process flock already serializes our writers |
| Snapshot assembly | claude-swap → `switcher.accounts_snapshot` one-pass + `SnapshotSource` reconcile across two fetch lanes | Two lanes exist only because its engine fetches separately; ours has one poller until M9 | `CollectAccountsView` use case (store + slot + dir + cache + clock ports) + a single refresh worker with a generation guard; no `SnapshotSource` reconcile — revisit when M9's engine owns its own cadence |
| `is_active` resolution | claude-swap → sequence-file active pointer; ours → live `oauthAccount.accountUuid` vs registry pointer | The pointer drifts; the live config is truth (ADR-0009 comment in `cmd_usage`) | View carries live-resolved `active_name` (same rule as `StatusAccount`/`SwitchAccount._capture`) — the uuid→name match is extracted into a domain service shared by all three |
| Blocking work | claude-swap → everything switcher-side in `run_worker(thread=True)`, results via `call_from_thread` | Textual's loop must never touch files/network | Same — every port/use-case call happens in thread workers; the UI mutates reactives only |
| Action results | claude-swap → `run_action` captures ANSI stdout, `OutputModal` renders it | Our use cases return typed results (`SwitchResult` etc.), not printed text | Notifications + modals render typed results directly; `switch_message` moves from `cli/json_output.py` to `switch_account.py` so both transports share the wording — no stdout capture |
| Account add in-TUI | claude-swap → capture current login / paste token (instant, no subprocess) | Our `add` launches an interactive `claude` login subprocess (ADR-0004 login-at-source); under Textual that needs `App.suspend()` — a new risk surface | Not offered in the TUI; the empty-state/menu copy points at `cam add <name>` (decided at pickup) |
| Theme | claude-swap → persisted `ui.theme` (dark/light/auto) + OSC-11 detection in cooked mode | Auto-detect's only consumer is a setting we can't persist until M9 (`settings.json`, GAP-007) | `CAM_DARK` + `CAM_LIGHT` + `ctrl+t` in-memory toggle; `appearance.py` deferred to whenever a persisted `ui.theme` exists |
| Auto view | claude-swap → real `AutoSwitchEngine` hosted, opens dry-run | The engine is M9 (`auto_tick`, cooldown, hysteresis, SIGTERM) | Preview-only screen: fixed `DRY-RUN` badge, active panel, "Next best" ranking by `binding_pct`, decision log fed by `switch.execute(strategy="best", dry_run=True)` — the exact selection path a real switch takes — logged on outcome change |
| Threshold source | claude-swap → `settings.json` + session adjust (`t`, arrows) | No settings until M9; session adjust exists to steer a live engine we don't have | Bars draw the tick at the fixed default 90 (docs/architecture.md §6); no adjust mode |
| Account identity on rows | claude-swap → slot numbers + aliases | We are name-keyed; aliases are a v1 non-goal (architecture §11) | Rows key on `name`; `[disabled]`/`[quarantined]` markers mirror `cam list` wording |
| Bare invocation | claude-swap → bare `cswap` on a tty opens the TUI | Changes our no-arg exit-2-usage contract for no request | `cam tui` + `cam watch` are explicit subcommands; bare `cam` keeps printing usage |
| `full` refresh (`f` key) | claude-swap → `full=True` accepted but plan-capped ("no faster than a normal pass") | Same policy holds for our `poll_due` gate | `f` requests a normal tick; eligibility decides what actually fetches |
| Async test harness | claude-swap → pytest-asyncio `@pytest.mark.asyncio` Pilot tests | New dev dep vs `asyncio.run` wrappers | pytest-asyncio pinned in `dependency-groups.dev` (ADR-0002 locks runtime deps only; dev toolchain already carries pinned test plugins) |

## Gap analysis — what we already have vs the references

| Concern | Ours today (file) | Best reference (file) | Gap |
| ------- | ----------------- | --------------------- | --- |
| TUI package | absent — `textual` pinned (`pyproject.toml`), deptry DEP002 ignored until the component lands | claude-swap `tui/` | absent |
| Fetch eligibility enforcement | `src/claude_acc_manager/usage/application/use_cases/fetch_account_usage.py` — fresh-cache serve only; `poll_due`/`in_backoff` never consulted (`cache_trust.in_backoff` renders JSON only) | claude-swap `usage_store.py` `reserve` (~L993) | present and partial — plan computed and persisted, never enforced |
| Poll-due predicate | absent — `poll_policy.plan_after_fetch` writes `next_poll_at_s`; nothing reads it | claude-swap `usage_store.py` `_row_eligible` | absent |
| Coherent account view for a UI | `list_accounts.py` + `status_account.py` + `usage_cache.load` exist separately; no one-pass view | claude-swap `models.py` `AccountsSnapshot` + `switcher.py` `accounts_snapshot` | absent |
| uuid→name live match | duplicated in `status_account.py` `execute` and `switch_account.py` `_match` | — | present, duplicated — extract a domain service |
| Quarantine on `permanent_auth_error` | `cli/commands.py` `_quarantine_dead_lineage` — transport-local | claude-swap `switcher.py` `_collect_usage_entries` (~L4984: tombstones dead lineages mid-collect) | present but unreachable outside `cmd_usage` — extract a use case |
| Weekly pace marker | absent | claude-swap `pace.py` `compute_pace` | absent |
| Usage bars / cards / minis | absent | claude-swap `tui/widgets.py` | absent |
| Dashboard + nested menu | absent | claude-swap `tui/dashboard.py` `DashboardScreen` | absent |
| Switch / watch screens | absent | claude-swap `tui/dashboard.py` `AccountListScreen`/`SwitchScreen`/`WatchScreen` | absent |
| Auto view | absent — engine itself is M9 | claude-swap `tui/autoview.py` `AutoScreen` | absent — preview surface only this milestone |
| Modals | absent | claude-swap `tui/modals.py` `ConfirmModal` | absent (token/output modals not ported — see Deviations) |
| Theme | absent — the CLI prints plain text, no `printer.py` equivalent | claude-swap `tui/theme.py` `Palette`/`CSWAP_*` | absent |
| Entry commands | absent — `cli/parser.py` has no `tui`/`watch` | claude-swap `cli.py` ~L1442 | absent |
| Pilot test harness | absent — `test/support/` fakes cover every port already | claude-swap `tests/test_tui.py` | absent (fakes present, harness missing) |

## Deviations

- `AddTokenModal`, `add-login`/`add-token` menu entries are not ported — setup-token/API-key accounts are non-goals (architecture §11) and our add is an interactive subprocess login, not a credential capture; the dashboard's empty state and menu hint at `cam add <name>`.
- No theme persistence and no OSC-11 background detection — `settings.json` is M9 (GAP-007); `ctrl+t` cycles dark/light for the session only.
- No `OutputModal`/ANSI-capture action runner — our use cases return typed results (`SwitchResult`); notifications and the confirm modal render those. `switch_message` moves to `accounts/application/use_cases/switch_account.py` so `cli` and `tui` share the wording.
- No `SnapshotSource` reconcile / second store-only lane — one poller exists until M9's engine; a generation counter drops late worker results.
- No engine in the auto view: fixed `DRY-RUN` badge, threshold tick at the default 90, candidate ranking + decision log via the real `best` selection path in dry-run. `set_store_only`, `apply_threshold`/`wake`, `clear_poll_policy_inputs` arrive with M9's engine.
- No usage sentinels (`api_key`, `token_expired`, `keychain_unavailable`) — those states don't exist in our model (ADR-0005, file-only credentials); a card renders quarantine/disabled markers and `usage unavailable · <last_error>` instead.
- No spend/`$$` row — `extra_usage` is deferred by ADR-0012.
- Fetch gating tightens `cam usage`: a stale-but-not-due account now serves last-good (while `trust_ok` holds) instead of refetching — the reference's on-demand semantics, adopted so every surface shares one cadence.
- Bare `cam` keeps printing usage (exit 2) — `cam tui`/`cam watch` are the explicit entries.
- Claims/fencing from `reserve` are not ported — our store's single flock already serializes writers; there is no second collector until M9.

## Open decisions

None — scope questions (auto view preview-only, gate `execute` for all callers, no in-TUI add, include watch) were settled with the user at pickup, each on the cited evidence.

## Surface

| Layer | Files |
| ----- | ----- |
| domain | `src/claude_acc_manager/usage/domain/services/poll_policy.py` (+`poll_due`); `src/claude_acc_manager/usage/domain/services/pace.py` (new); `src/claude_acc_manager/accounts/domain/services/` (new uuid→name match shared by `status_account.py`, `switch_account.py`, `collect_accounts_view.py`) |
| application (ports / use cases) | `src/claude_acc_manager/usage/application/use_cases/fetch_account_usage.py` (+gates); `src/claude_acc_manager/accounts/application/use_cases/collect_accounts_view.py` (new); `src/claude_acc_manager/accounts/application/use_cases/quarantine_dead_lineage.py` (new; replaces the `cmd_usage`-local `_quarantine_dead_lineage` and `QuarantineAccount`'s only caller); `src/claude_acc_manager/accounts/application/use_cases/switch_account.py` (+`switch_message` moved here) |
| tui | `src/claude_acc_manager/tui/__init__.py` (`run(use_cases, *, start)`), `src/claude_acc_manager/tui/app.py`, `src/claude_acc_manager/tui/dashboard.py`, `src/claude_acc_manager/tui/autoview.py`, `src/claude_acc_manager/tui/widgets.py`, `src/claude_acc_manager/tui/modals.py`, `src/claude_acc_manager/tui/formatting.py`, `src/claude_acc_manager/tui/theme.py`, `src/claude_acc_manager/tui/cam.tcss` |
| cli | `src/claude_acc_manager/cli/parser.py` (+`tui`, `watch`); `src/claude_acc_manager/cli/commands.py` (lazy `tui` handlers, quarantine rewire); `src/claude_acc_manager/cli/context.py` (`UseCases` +`collect_view`, +`quarantine_dead_lineage`, −`quarantine`); `src/claude_acc_manager/cli/json_output.py` (`switch_message` import moved) |
| composition root | `src/claude_acc_manager/__main__.py` (wire the two new use cases) |
| config | `pyproject.toml` (import-linter `tui` contract — forbid `*.infrastructure` and `claude_acc_manager.cli`; deptry DEP002 ignore removed; pytest-asyncio dev pin) |
| tests | `test/unit/usage/` (+`test_pace.py`, gate tests in `test_fetch_account_usage.py`), `test/unit/accounts/` (+`test_collect_accounts_view.py`, `test_quarantine_dead_lineage.py`, match-service tests), `test/unit/tui/` (helpers + Pilot tests), `test/support/use_cases.py` (shared fake-backed `UseCases` builder, extracted from `test_cli.py`'s `_use_cases`), `test/unit/test_cli.py` |

## Tasks

One TDD unit each, one conventional commit each. Small enough that a unit takes well under an hour; if it does not, decompose further.

- [x] T1 — `poll_policy.poll_due` + `in_backoff`/`poll_due` gates inside `FetchAccountUsage.execute` (not-eligible → serve last-good while `trust_ok`, `last_error` = `"backoff"`/`"not-due"`); update the M5 tests pinning eager fetch. `feat(usage): gate fetches on the persisted poll plan and backoff`
- [x] T2 — `usage/domain/services/pace.py` `compute_pace` port (pure). `feat(usage): compute weekly pace for ahead-of-schedule markers`
- [x] T3 — uuid→name domain-service extraction + `CollectAccountsView` + `AccountsView`/`AccountView` + `UseCases.collect_view` wiring. `feat(accounts): collect a one-pass accounts view for the TUI`
- [x] T4 — `QuarantineDeadLineage` use case; rewire `cmd_usage`; drop `QuarantineAccount`/`UseCases.quarantine`. `feat(accounts): share the permanent-auth-error tombstone path`
- [x] T5 — `tui/` foundation: `theme.py` (`Palette`, `CAM_DARK`, `CAM_LIGHT`), `cam.tcss`, `app.py` (`CamApp` reactives, 3s tick → single-flight worker `collect → gated fetch pass → re-collect`, generation guard, `busy`), `__init__.py` `run()` (textual imports inside), `cam tui`/`cam watch` parsers + lazy handlers, `__main__` wiring, import-linter `tui` contract, pytest-asyncio pin, deptry DEP002 removal. `feat(tui): app shell, poll loop, and cam tui/watch entries`
- [ ] T6 — `tui/formatting.py` (`format_duration`, `format_age`, `reset_text`, `reset_clock`, `clock_stamp`). `feat(tui): usage display formatters`
- [ ] T7 — `tui/widgets.py` renderers (`bar_cells`, `usage_bar`, `usage_rows` incl. pace marker, `account_card_text`, `mini_account_text`) + `AccountsPanel`/`AccountCard`/`AccountItem`/`MenuItem`. `feat(tui): usage bars and account cards`
- [ ] T8 — `DashboardScreen` + nested menu (switch, watch, auto, enable/disable submenu, remove submenu, theme submenu, quit). `feat(tui): dashboard screen and menu`
- [ ] T9 — `AccountListScreen` + `SwitchScreen` (Enter/`b` → worker → `notify(switch_message)`). `feat(tui): switch screen`
- [ ] T10 — `WatchScreen` (armed-selection monitor). `feat(tui): watch screen`
- [ ] T11 — `ConfirmModal` + enable/disable + remove actions. `feat(tui): enable, disable, and remove actions`
- [ ] T12 — `AutoScreen` preview (badge, summary, "Next best" ranking, dry-run `best` decision log). `feat(tui): auto preview screen`
- [ ] T13 — ship: manual validation above; gate numbers in the closing commit body; backlog M8 → `shipped`; parity-matrix GAP-005 row corrected; this file deleted. `docs(backlog): ship M8 — TUI dashboard, switch, watch, auto preview`

## Out of scope

- The auto-switch engine (`auto_tick`, `auto` loop, threshold/cooldown/hysteresis, SIGTERM, urgent-mode poll policy) — M9 (GAP-004).
- `settings.json` (threshold/interval/cooldown/strategy/theme persistence) — M9 (GAP-007).
- In-TUI `add` (interactive `claude` login under `App.suspend()`), token/API-key modal flows — see Deviations.
- Snapshot claim leases / multi-lane reconciliation — needed only when a second fetcher exists (M9).
- macOS/keychain, aliases, `extra_usage` spend row, session merging, export/import — v1 non-goals (architecture §11).
