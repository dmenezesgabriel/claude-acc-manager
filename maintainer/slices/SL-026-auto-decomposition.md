# SL-026 — auto decomposition: collection collaborator + ranking request

Milestone: M25 · State: open · Depends on: SL-025 · Closes: —

> PRD for M25 (AUD-002, AUD-003). Evidence: `maintainer/research/architecture-audit.md` rows AUD-002 and AUD-003. Delete this file when the milestone ships.

## Outcome

Afterwards, `src/claude_acc_manager/auto/application/auto_engine.py` is under the 500-line ceiling because the tick's scheduled-collection stage lives in an injected `CollectFleetUsage` collaborator, and `src/claude_acc_manager/auto/domain/services/auto_rank.py` reads named `RankingRequest` fields instead of re-passing an 11–14-parameter positional list twice per call chain.

## Exit gate

`uv run pre-commit run --all-files` clean · full `uv run pytest` green · then the manual validation below. Measurements go in the closing commit's body.

1. `wc -l src/claude_acc_manager/auto/application/auto_engine.py` < 500 — the milestone's headline check (target ~365).
2. `wc -l src/claude_acc_manager/auto/domain/services/auto_rank.py` < 500 — the signature collapse is expected to land it under too (target ~450–475); if it lands over, record the measured number in the closing commit body and leave the file for a later concept-boundary split — the milestone row requires it of the engine only.
3. `uv run pytest test/unit/auto test/unit/test_auto_output.py` green — the engine suite asserts through `tick()` only, so a behavior-true extraction keeps every test green unmodified.
4. `uv run mutmut results` shows no `survived`/`no tests`/`timeout` for `auto_engine.py`, `auto_rank.py`, `collect_fleet_usage.py` — mutmut is incremental and retests every moved/rewritten function; `grep -n "pragma: no mutate" src/claude_acc_manager/auto/` must show each pragma still attached to the line it justifies.
5. `uv run cam auto --once --dry-run` ticks against the real store and prints the same event sequence shape as before (PollEvent → NoSwitch/Switch) — a smoke that the rewired composition root assembles.

## Who else implements this

A stage-collaborator extraction and a parameter-object are our own structural calls, not ports — but upstream faces both problems and answers them differently, which is the decision this milestone names.

| Repo | Has it | Entry points | Approach in one line |
| --- | --- | --- | --- |
| claude-swap | PARTIAL | `research_repos/claude-swap/src/claude_swap/autoswitch.py` | collection is delegated but along the resource axis — the engine calls `switcher.usage_entries_by_account` (`switcher.py:1721`) so fetching lives in the 7431-line switcher god-object, and the "collector" is a named concept (`autoswitch.py:659`) without a stage boundary; the twice-passed ranking list is answered by a `def _rank(**kw)` closure (`autoswitch.py:1103`) that captures the tick's kwargs once and re-invokes `_rank_candidates` (`autoswitch.py:1755`, keyword-only, 10 params) |
| ai-usagebar | ABSENT | `research_repos/ai-usagebar/src/account.rs` `fn switch` (~442) | `account switch` is a one-shot manual command; no auto engine, no tick, no ranking pipeline |
| toad | ABSENT | — | a TUI shell; no usage engine at all |
| claude-code itself | — | not applicable | the vendor side; no auto-switch behavior to interoperate with |

**Count:** 0 of the references implement either shape. claude-swap's `**kw` closure is the disagreement this milestone resolves: an untyped dict threaded through a nested function versus a frozen dataclass checked by pyright strict. Both decompositions are therefore audit-driven (AGENTS.md's file ceiling + explicit-types rules, ADR-0010), not ports.

## Implementation inventory

The work is a move-and-collapse inside our own tree; the reference files below exist to pin the disagreement evidence.

### claude-swap

| Concern | Files |
| --- | --- |
| The resource-axis collection we diverge from | `research_repos/claude-swap/src/claude_swap/autoswitch.py` — `AutoSwitchEngine` monolith calling `switcher.usage_entries_by_account(fetch=...)` (~1192); `research_repos/claude-swap/src/claude_swap/switcher.py` — `usage_entries_by_account` (~1721) |
| The `**kw`-closure we diverge from | `research_repos/claude-swap/src/claude_swap/autoswitch.py` — `_rank(**kw)` closure (~1103) + `_rank_candidates` keyword-only signature (~1755) |

## Trade-offs and what we adopt

| Axis | Options seen (repo → approach) | Trade-off | Our choice, and why |
| ---- | ---------------------------- | --------- | ------------------- |
| Collaborator seam | internal composition (`self._collector = CollectFleetUsage(...)` inside `__init__`, constructor unchanged) vs injected `FleetCollectorPort` (engine drops the 4 collection-only ports) | composition keeps a 13-param constructor that forwards four ports untouched; injection is the `FreshenPort` convention — "the engine depends on the capability, not the use-case class" (`auto/application/ports.py`) | injected port: `auto/application/ports.py` gains `FleetCollectorPort` + the `FleetCollection` result (frozen dataclass — `SwitchResult` lives beside its port the same way in `accounts/application/ports.py`); `AutoEngine.__init__` goes 13 → 10 params |
| Who emits `PollEvent` | collector takes `emit` and emits inside `execute` vs result carries a ready-built `poll_event` the engine emits | a side-effecting port hides an event in a data contract; carrying the event keeps the engine the single decision→event site, like `FreshenStatus`/`SwitchResult` verdicts | `FleetCollection.poll_event` — the `relevant_windows` projection is the collector's product; emission order stays in `_tick_inner` |
| `state` in `RankingRequest` | inside (one-arg `choose(request)`) vs outside (`choose(request, state)`) | `AutoState` is engine memory reloaded under the state lock in `_perform`, not a tick measurement | `state` stays a separate parameter on `choose`/`no_return_account`/`_bar_released` |
| Scope of the fold | every auto_rank function takes the request vs only the flagged 11–14-param signatures | folding `left_account_recovered`/`every_account_above_threshold`/`recovery_is_useful` (4–6 params each) churns ~26 more test sites for no smell removal | only `choose`/`rank_candidates`/`no_return_account`/`_admission` family + `_bar_released`; small helpers keep explicit signatures — `rank_candidates` unpacks `request.*` fields when calling them |
| Twice-passed list | claude-swap → `def _rank(**kw)` closure capturing kwargs; ours → dataclass | `**kw` is untyped (pyright can't check a dict), nests logic inside `_tick_inner`, and still re-passes the whole dict to a 10-param signature | `RankingRequest` frozen dataclass in `auto_rank.py` (single consumer — cohesion beats a standalone `auto/domain/` module today); private `_FleetInputs` frozen dataclass absorbs `_fleet_census` + `all_above` + `barred` so `_admission(request, fleet, name, h, index)` is 5 params |

## Gap analysis — what we already have vs the references

| Concern | Ours today (file) | Best reference (file) | Gap |
| ------- | ----------------- | --------------------- | --- |
| Collection stage boundary | `auto/application/auto_engine.py` — 9 methods + `_fetch_for` inline in the engine (~lines 244–435) | claude-swap `autoswitch.py`/`switcher.py` — delegated along the resource axis, no stage boundary | present and correct — orchestration sits in the wrong class, not missing logic |
| Ranking input bundling | `auto/domain/services/auto_rank.py` — `choose`/`rank_candidates`/`_admission` re-pass 11–14 params; `rank_candidates` called twice with the identical list | claude-swap `autoswitch.py` `_rank(**kw)` — same problem, closure answer | present — the repeated list exists; only its shape is unfixed |
| Twice-invoked rank | `choose` module function re-passes the list | `_rank` closure re-invokes on captured kwargs | complete — same control flow, different param mechanics |

## Deviations

- The collaborator is a use case (`application/use_cases/collect_fleet_usage.py`, VerbNoun + one `execute`) even though only the engine calls it — `FreshenTarget` is the same engine-internal shape, and AGENTS.md's home rules leave no fourth place for port-orchestrating classes.
- `test/support/engine_harness.py` wires the real `CollectFleetUsage` over the existing fakes — no `FakeFleetCollector` is added; the suite fakes at the inner-port level today and gains nothing from a second seam.

## Open decisions

None — the audit names both dispositions and the disagreements above are resolved in the trade-off table.

## Surface

| Layer | Files |
| ----- | ----- |
| domain | `src/claude_acc_manager/auto/domain/services/auto_rank.py` — + `RankingRequest`, + private `_FleetInputs`, signature collapse |
| application (ports / use cases) | `src/claude_acc_manager/auto/application/ports.py` — + `FleetCollectorPort`, + `FleetCollection`; `src/claude_acc_manager/auto/application/use_cases/collect_fleet_usage.py` — new; `src/claude_acc_manager/auto/application/auto_engine.py` — −~190 lines, 13 → 10 params |
| infrastructure | — |
| cli / tui | `src/claude_acc_manager/cli/commands.py` — wire `CollectFleetUsage` into `cmd_auto` |
| tests | `test/support/engine_harness.py` — build `h.collector` over existing fakes; `test/unit/auto/application/test_auto_engine.py` (2 direct constructions), `test/unit/auto/application/test_auto_loop.py` (1) — pass `collector=`; `test/unit/auto/domain/services/test_auto_rank.py` — `_request()` helper + ~57 call-site rewrites |

## Tasks

One conventional commit each. Both refactors are behavior-preserving: the engine suite asserts through `tick()` and the auto_rank suite pins every gate, so RED is already satisfied — each GREEN is the existing suite staying green through the move.

- [ ] T1 — `refactor(auto): extract the tick's collection stage into CollectFleetUsage` — `FleetCollectorPort` + `FleetCollection` in `auto/application/ports.py`; new `use_cases/collect_fleet_usage.py` carrying `_eligible_candidates`/`_plan`/`_stale_candidate_plan`/`_escalates`/`_escalate_all`/`_reset_parked`/`_snapshots`/`_fetch_errors`/`_fetch_for`/`_poll_event`; engine takes `collector`, drops `store`/`account_files`/`usage_cache`/`fetch`, emits `collected.poll_event`; wire `commands.py` + `engine_harness.py` + the 3 direct `AutoEngine(...)` test sites.
- [ ] T2 — `refactor(auto): bundle ranking inputs into RankingRequest` — frozen `RankingRequest` (10 fields, no `state`) + private `_FleetInputs` in `auto_rank.py`; `choose(request, state)`, `rank_candidates(request, no_return)`, `no_return_account(request, state)`, `_bar_released(request, state, came_from)`, `_admission(request, fleet, name, h, index)`, `_healthy_landing(request, h, index)`, `_all_spent_admission(request, fleet, h, snapshot)`, `_spent_fallback(request, fleet, h, recovery_ts)`; `_fleet_census` folds into the `_FleetInputs` build; `_request()` test helper + ~57 site rewrites; engine builds the request once and calls `auto_rank.choose(request, state)`.
- [ ] T3 — `docs(maintainer): M25 shipped — auto decomposition landed` — check this PRD's boxes, mark the backlog row `shipped`, delete this file, record exit-gate numbers in the commit body.

## Out of scope

- `tui/app.py`'s action-runner split and its private-access test rework — AUD-001/AUD-017, owned by M26.
- `test_auto_engine.py`'s 965 lines and `test_auto_rank.py`'s 1,433 — AUD-019/AUD-020 file-ceiling splits, owned by M27.
- Any behavioral change to poll cadence, escalation margins, or the no-return guard — the milestone is a move, not a tuning pass.
