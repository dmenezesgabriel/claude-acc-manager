# SL-028 — Test-suite decomposition

Milestone: M27 · State: open · Depends on: — · Closes: AUD-019, AUD-020 (`maintainer/research/architecture-audit.md`)

> PRD for the executing session: never guess, never assume. Every `research_repos/` path below was verified with `test -e` in the writing session. Every `test/` path was measured with `wc -l` on 2026-10-13.

## Outcome

Every file under `test/` is ≤500 lines: the 12 over-ceiling suites split along their existing `Test*` class seams, and the helpers those seams share move to `test/support/` so no test body changes.

## Exit gate

`uv run pre-commit run --all-files` clean · `find test -name '*.py' | xargs wc -l | awk '$1 > 500'` prints only the total row · `uv run pytest test/unit -n auto --cov --cov-branch --cov-fail-under=95` green with ≥2,035 collected (the pre-split count — assert it per commit so no test is dropped) · `grep -rn "test_cli\.py" src/ test/ docs/` returns zero hits. Numbers go in the closing commit body.

## Who else implements this

| Repo | Has it | Entry points | Approach in one line |
| --- | --- | --- | --- |
| claude-swap | ABSENT | `research_repos/claude-swap/tests/test_switcher.py` (12,488 lines), `research_repos/claude-swap/tests/` (flat, per-module files) | flat `tests/` with mega-files — no file-size ceiling convention |
| ai-usagebar | ABSENT | `research_repos/ai-usagebar/tests/` (`public_api.rs`, `anthropic_e2e.rs`, `live.rs`) | Rust: unit tests inline in `src/`, `tests/` holds a few e2e files — no ceiling |
| toad | ABSENT | `research_repos/toad/src/` — no `tests/` directory exists | no test suite to decompose |
| claude-code itself | — | n/a | not applicable |

**Count:** 0 of 3 references enforce a test-file ceiling. The split is ours — the 500-line ceiling is AGENTS.md / docs/architecture.md §10 applied to `test/`, same posture as SL-027: nothing to port, the mechanism is the seam the audit already named (per-command areas for AUD-019; per-src-module class groups for AUD-020).

## Implementation inventory

The seam inventory is our own suite — every file is already organized into named `Test*` classes, so splits are class-grain moves with no test-body edits.

### Shared-helper rule

`--import-mode=importlib` + `pythonpath=["src","test"]` (pyproject) means sibling test modules cannot import each other: a helper used by two split files must live in `test/support/` (the named-fake/composition-helper package — `support/use_cases.py`, `support/engine_harness.py`, `support/tui_app.py` are the precedent). Split files import the public names back `as _x` so test bodies stay byte-identical (`EngineHarness as _Harness` is the existing idiom). Tiny per-file helpers that are already duplicated across suites — `FIXTURES` path constants, `load_fixture`, `file_mode`, `_iso` — stay local per split file.

### `test/unit/test_cli.py` (4,343) → 18 flat files + `test/support/cli_rigs.py`

Flat placement: the cli-layer suites already live at `test/unit/` root (`test_main.py`, `test_human.py`, `test_auto_output.py`); a `test/unit/cli/` package would half-mirror and orphan them. `cli_rigs.py` exports (former private names): `run_cli` (`_run`), `run_cli_tty` (`_run_tty`), `cli_config_for` (`_config_for`), `park_account` (`_park`), `cache_usage` (`_cache_usage`), `snap_used` (`_snap_used`), `auto_credentials` (`_auto_credentials`), `auto_rig` (`_auto_rig`), `dead_lineage_rig` (`_dead_lineage_rig`), `until` (`_until`), `upgrade_cli` (`_upgrade`), `offering_use_cases` (`_offering_use_cases`).

| New file | Classes moved | Est. |
| --- | --- | --- |
| `test_cli_accounts.py` | TestAddCommand, TestRemoveCommand, TestEnableDisableCommands | ~240 |
| `test_cli_list.py` | TestListCommand, TestListJsonCommand | ~420 |
| `test_cli_status.py` | TestStatusCommand, TestStatusJsonCommand | ~270 |
| `test_cli_doctor.py` | TestDoctorCommand | ~90 |
| `test_cli_usage.py` | TestUsageCommand | ~300 |
| `test_cli_usage_json.py` | TestUsageJsonCommand | ~325 |
| `test_cli_switch.py` | TestSwitchCommand mechanics: named/unknown/both-error, lock timeout (text+json), bare rotate, unmanaged preserved, already-active, scoped-shell, model flag, no-prior-login, wiped-credential, refused-contract, help, unknown-strategy | ~335 |
| `test_cli_switch_plans.py` | TestSwitchCommand strategy/stay: best, next-available, dry-run ×2, candidates-exhausted, no-valid-target, best-no-measurement, best-already-leads | ~280 |
| `test_cli_switch_json.py` | TestSwitchJsonCommand | ~295 |
| `test_cli_auto_once.py` | `cam auto --once` decisions/exit-codes/flags/quarantine | ~370 |
| `test_cli_auto_json.py` | `cam auto --once/--loop --json` event envelopes | ~320 |
| `test_cli_auto_loop.py` | loop SIGTERM/banner/emit-flush + strategy tests | ~270 |
| `test_cli_config.py` | TestConfigCommand | ~230 |
| `test_cli_entry.py` | TestArgParsing, TestVersionFlag, TestBareCamTui, TestRootGuard, TestTuiEntryPoints | ~390 |
| `test_cli_help.py` | TestHelpText | ~220 |
| `test_cli_styling.py` | TestHumanStyling | ~335 |
| `test_cli_upgrade.py` | TestUpgradeCommand | ~245 |
| `test_cli_update.py` | TestUpdateNotice, TestUpdateAutoApply, TestAutoUpdateEvent | ~345 |

Repoints when `test_cli.py` is deleted: `src/claude_acc_manager/cli/commands.py` module docstring (`test/unit/test_cli.py` → `test/unit/test_cli_*.py`) and `test/unit/test_auto_output.py` docstring (`test_cli.py` → `test_cli_auto_once.py`/`test_cli_auto_loop.py`).

### `test/unit/accounts/`

| Source | New files (classes) | Shared extraction |
| --- | --- | --- |
| `application/use_cases/test_switch_account.py` (1,054) | `test_switch_account_flow.py` (TestManagedToManaged, TestOutgoingClasses ~400) · `test_switch_account_strategies.py` (TestStrategies, TestDryRun ~375) · `test_switch_account_rollback.py` (TestRollback, TestRollbackNotes ~260) · `test_switch_account_gates.py` (TestScopedShell, TestContractGate ~250) | `test/support/switch_rig.py`: `SwitchRig` (was `_Wiring`, ~54 ln) + `creds`/`config`/`wiped`/`account` — all four helpers are used directly by every group |
| `infrastructure/test_file_account_store.py` (891) | `test_file_account_store_registry.py` (TestRegistryValidationMessages, TestRegistrySchema ~425) · `test_file_account_store.py` residue (StoreAdaptsPort, AccountDir, Upsert, Get, Remove, SetEnabled, ActivePointer, LockedMutations ~375) · `test_file_account_store_quarantine.py` (TestQuarantine, TestQuarantinedEntryValidation + local `_quarantine_entry` ~220) | `test/support/file_store_rigs.py`: `file_store` (`make_store`), `store_account` (`make_account`), `registry_doc`, `write_registry` |
| `infrastructure/test_active_slot.py` (557) | `test_active_slot_credentials.py` (ActiveSlotPort, ReadCredentials, WriteCredentials, CredentialsPath, CredentialMutationsHoldStorageWrite, DeleteCredentials ~310) · `test_active_slot_config.py` (ReadConfig, WriteConfig, SalvageTornConfig, DeleteConfig, SpliceConfigOauthAccount ~315) | none — `file_mode`/`FIXTURES` stay per-file (existing dup convention) |

### `test/unit/usage/`

| Source | New files (classes) | Shared extraction |
| --- | --- | --- |
| `application/use_cases/test_fetch_account_usage.py` (1,155) | `test_fetch_account_usage_cache.py` (ServesFreshCache, FetchEligibilityGates, FetchesAndCachesOnAStaleCache, NoCredential ~425) · `test_fetch_account_usage_plan.py` (PollPlanThreadsThroughEveryFactor, RefreshBeforeFetch + local `_refreshing_use_case`, UrgentThreshold ~450) · `test_fetch_account_usage_errors.py` (ContractGate, FetchFailure, ForceFetch ~445) | `test/support/fetch_usage_rig.py`: `fetch_usage_rig` (was `make_use_case`, ~35 ln) + the `SNAPSHOT`/`CREDENTIAL`/`HALF` constants it needs; `_iso` stays per-file |
| `domain/services/test_poll_policy.py` (711) | `test_poll_policy_plan.py` (`_plan`+`HALF`/`NOW` + IntervalAdaptation, ExhaustedFloor, ResetCapping, Jitter, Post429Floor, Post429Aimd, BudgetInvariants, UrgentMode ~330) · `test_poll_policy_resets.py` (`_snapshot` + BindingPct, ParseResetEpoch, LimitingResetEpoch, EarliestFutureResetEpoch, PollDue, EarliestResetEpoch ~270) · `test_poll_policy_due.py` (`_entry` + PlanOversleepsInterval, DueCandidate ~215) | none — grouping follows helper locality exactly (`_plan` users verified at lines ≤232 and 462–531, all inside the plan group) |
| `infrastructure/test_anthropic_oauth.py` (522) | `test_anthropic_oauth_usage.py` (IsAUsageApiPort, FetchUsageSends, FetchUsageParses, FetchUsageRaises ~200) · `test_anthropic_oauth_refresh.py` (RefresherPort, RefreshSends, RefreshParses, RefreshRejectsMalformed, RefreshRaises, Redaction ~275) · `test_anthropic_oauth_identity.py` (IdentityLookupPort, ResolveSends, ResolveParses, ResolveFailsOpen, Allowlist ~170) | none — `FIXTURES`/`load_fixture` stay per-file |

### `test/unit/auto/`

| Source | New files (classes) | Shared extraction |
| --- | --- | --- |
| `domain/services/test_auto_rank.py` (1,648) | `test_auto_rank_triggers.py` (ClassifyTrigger, InCooldown, BindingRecoveryEpoch, EveryAccountAboveThreshold, RecoveryIsUseful ~215) · `test_auto_rank_candidates.py` (RankCandidates ~435) · `test_auto_rank_recovery.py` (RecoveryAxis, SpentFallback ~460) · `test_auto_rank_no_return.py` (NoReturnAccount, LeftAccountRecovered, EarliestRecoveryEpoch ~395) · `test_auto_rank_choose.py` (Choose ~420) | `test/support/rank_requests.py`: `iso`, `snap`, `request` (was `_iso`/`_snap`/`_request`, ~53 ln) — used by every class |
| `application/test_auto_engine.py` (989) | `test_auto_engine_selection.py` (NoActive, LoopFacingFields, TriggerGates, CandidateSelection, NeverRaises + local `_reasons`/`_RaisingIdentity` ~300) · `test_auto_engine_switch.py` (SwitchPath, LockedRecheck + local `_CooldownOnLockAutoState` ~320) · `test_auto_engine_collection.py` (ScheduledCollection, StaleCandidatePlan ~460) | none — `support/engine_harness.py` already shared |

### `test/unit/tui/`

| Source | New files (classes) | Shared extraction |
| --- | --- | --- |
| `test_widgets.py` (889) | `test_widgets_bars.py` (BarCells, UsageBar, UsageRows ~310) · `test_widgets_cards.py` (AccountCardText, MiniAccountText, FormatDurationReuse + local `_card_plain` ~410) · `test_widgets_panel.py` (AccountsPanel + `_WidgetApp` + AccountWidgets ~415) | `test/support/tui_views.py`: `iso`, `view`, `snapshot` — `_view`/`_snapshot`/`_iso` are already duplicated between test_widgets.py and test_visuals.py; extract once for all five split files instead of copying to five |
| `test_visuals.py` (507) | `test_visuals_widgets.py` (`_WidthEcho`, `_WidthEchoVisual`, RulesKey, MultilineFlag, OptimalWidthDelegation, UsageBarVisual, MiniAccountVisual, AccountCardVisual ~320) · `test_visuals_strips.py` (StackedJoins, StripCache, RenderReturnsVisuals ~305) | shares `tui_views.py` |
| `test_app.py` (615) | `test_app_poll.py` (Defaults, PollLoop, SnapshotGuard, RefreshStatus, ManualRefresh, ThemeToggle, WatchStart, UpdateNotice + local `_RecordingFetchUsage`/`_BlockingCollectAccountsView` ~395) · `test_app_actions.py` (AccountActions, WorkerFailure + local `_RaisingFetchUsage` ~265) | none — fakes stay local (verified single-file usage) |

## Trade-offs and what we adopt

| Axis | Options seen (repo → approach) | Trade-off | Our choice, and why |
| ---- | ---------------------------- | --------- | ------------------- |
| `test_cli.py` destination | ours → flat `test_cli_<area>.py`; hypothetical `test/unit/cli/` package | a `cli/` package mirrors src more literally but orphans the three sibling flat cli-layer files and adds a relocation decision the audit didn't ask for | flat — matches the existing placement of `test_main.py`/`test_human.py`/`test_auto_output.py`; minimum diff |
| Helper locality | per-file copies vs `test/support/` extraction | tiny helpers (`FIXTURES`, `file_mode`, `_iso`, `load_fixture`) are already duplicated by convention; ≥35-line rigs used by every class are not | rigs → support; trivial consts → per-file |
| `tui` view builders | keep per-file copies ×5 vs extract to `test/support/tui_views.py` | the helpers are already duplicated between two files; splitting without extracting makes five copies | extract — the milestone must not worsen a known duplication |
| Class-name stability | rename classes per new file vs keep names | keeping `TestSwitchCommand` names stable preserves pytest node IDs (only the path changes) | keep names verbatim |

## Gap analysis — what we already have vs the references

| Concern | Ours today (file) | Best reference (file) | Gap |
| ------- | ----------------- | --------------------- | --- |
| CLI command suite | `test/unit/test_cli.py` (4,343) | claude-swap `tests/test_switcher.py` (12,488 — counterexample, not a model) | present, over ceiling — split per command area |
| Per-module suites | 11 files >500 (`maintainer/research/architecture-audit.md` AUD-020 row) | — | present, over ceiling — split per src-module aspect |
| Shared test rigs | `test/support/` (33 fakes + `use_cases.py`/`engine_harness.py`/`tui_app.py`) | — | complete — add six rig modules in the same idiom |

## Deviations

- Nothing ported; the milestone is internal to `test/` plus two docstring repoints (`cli/commands.py`, `test_auto_output.py`).
- New `test/support/` modules are rig-only — no `test/unit/support/` tests added, consistent with `use_cases.py`/`engine_harness.py`/`tui_app.py` (exercised by their consumers).

## Open decisions

None — the audit named the seams, pyproject named the import mechanism, the ceiling names the groupings.

## Surface

| Layer | Files |
| ----- | ----- |
| tests | `test/unit/test_cli.py` → 18 files; `test/unit/accounts/` → +9 files; `test/unit/usage/` → +9 files; `test/unit/auto/` → +8 files; `test/unit/tui/` → +7 files |
| tests (support) | `test/support/cli_rigs.py` · `test/support/switch_rig.py` · `test/support/file_store_rigs.py` · `test/support/fetch_usage_rig.py` · `test/support/rank_requests.py` · `test/support/tui_views.py` (all NEW) |
| src | `src/claude_acc_manager/cli/commands.py` (docstring repoint only) |

## Tasks

One unit per conventional commit, gate green at each. Per commit: `uv run pytest --collect-only -q | tail -1` count ≥2,035 and `find test -name '*.py' -newer maintainer/backlog.md | xargs wc -l` — every touched file ≤500.

- [ ] T1 — `test(cli)`: extract `test/support/cli_rigs.py`; repoint `test_cli.py`'s helper defs to imports.
- [ ] T2 — `test(cli)`: `test_cli_accounts.py`, `test_cli_list.py`, `test_cli_status.py`, `test_cli_doctor.py`.
- [ ] T3 — `test(cli)`: `test_cli_usage.py`, `test_cli_usage_json.py`.
- [ ] T4 — `test(cli)`: `test_cli_switch.py`, `test_cli_switch_plans.py`, `test_cli_switch_json.py`.
- [ ] T5 — `test(cli)`: `test_cli_auto_once.py`, `test_cli_auto_json.py`, `test_cli_auto_loop.py`.
- [ ] T6 — `test(cli)`: `test_cli_config.py`, `test_cli_entry.py`, `test_cli_help.py`, `test_cli_styling.py`, `test_cli_upgrade.py`, `test_cli_update.py`; delete `test_cli.py`; repoint `commands.py` + `test_auto_output.py` docstrings.
- [ ] T7 — `test(accounts)`: extract `test/support/switch_rig.py`; split `test_switch_account.py` → 4 files.
- [ ] T8 — `test(accounts)`: extract `test/support/file_store_rigs.py`; split `test_file_account_store.py` → 3 files.
- [ ] T9 — `test(accounts)`: split `test_active_slot.py` → 2 files.
- [ ] T10 — `test(usage)`: extract `test/support/fetch_usage_rig.py`; split `test_fetch_account_usage.py` → 3 files.
- [ ] T11 — `test(usage)`: split `test_poll_policy.py` → 3 files.
- [ ] T12 — `test(usage)`: split `test_anthropic_oauth.py` → 3 files.
- [ ] T13 — `test(auto)`: extract `test/support/rank_requests.py`; split `test_auto_rank.py` → 5 files.
- [ ] T14 — `test(auto)`: split `test_auto_engine.py` → 3 files.
- [ ] T15 — `test(tui)`: extract `test/support/tui_views.py`; split `test_widgets.py` → 3 files.
- [ ] T16 — `test(tui)`: split `test_visuals.py` → 2 files.
- [ ] T17 — `test(tui)`: split `test_app.py` → 2 files.
- [ ] T18 — `docs(maintainer)`: backlog row → shipped, delete this file, exit-gate numbers in commit body.

## Out of scope

- `test/unit/support/` tests for the new rig modules — rigs have no dedicated suite by convention.
- Moving `test_main.py`/`test_human.py`/`test_auto_output.py` into a `test/unit/cli/` mirror — the flat cli-layer placement predates this milestone and was not flagged.
- `test/unit/test_formatting.py`'s own `_iso` copy — under ceiling, untouched.
- Any src change beyond the `commands.py` docstring repoint.
