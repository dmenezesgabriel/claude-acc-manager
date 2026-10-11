# SL-023 — Port hygiene: dead port member, named headroom map, explicit subclassing

Milestone: M22 · State: open · Depends on: SL-022 (M21 audit) · Closes: AUD-006, AUD-012, AUD-013

> A PRD exists so the executing agent **never guesses and never assumes**. Every path below was verified on disk 2026-10-11 at `09644c4` (HEAD).

## Outcome

One sentence: the port surface carries only members with callers, the per-account headroom map has a name (`HeadroomMap`) instead of a repeated bare shape, and every port implementer subclasses explicitly — so `grep <PortName>` lands on every implementation.

## Exit gate

`uv run pre-commit run --all-files` clean · full `uv run pytest` green · then the validation below. Measurements go in the closing commit's body.

1. `grep -rn "salvage_torn_config" src/ test/` returns only `accounts/infrastructure/active_slot.py` (the adapter keeps it), `test/unit/accounts/infrastructure/test_active_slot.py` (concrete-class tests), and the `unclaimed_store.py` pragma comment — zero `ports.py` / `fake_active_slot.py` hits.
2. `grep -rn "Mapping\[str, float | None\]\|dict\[str, float | None\]" src/` returns only the `HeadroomMap` definition and `tui/account_list.py`'s `_stamps` (a different concept — fetched-at stamps, deliberately untouched).
3. `grep -rn "^class \(StatusAccount\|FetchAccountUsage\|FreshenTarget\|ActiveSlotAdapter\|UrllibHttpTransport\)" src/` shows each subclassing its port; pyright strict is the drift check.

This milestone is a pure refactor: no behavior changes, so the suite + pyright strict are the spec. There is nothing new to TDD — the tasks below are mechanical units, one commit each. The audit's gate note applies: a `refactor` that removes code must keep mutation green; check for `# pragma: no mutate` orphans.

## Who else implements this

The three findings are boundary-shape questions internal to this codebase's port architecture (ADR-0010) — the references inform the *capabilities* behind the boundaries, not the boundaries themselves.

| Repo | Has it | Entry points | Approach in one line |
| --- | --- | --- | --- |
| claude-swap | PARTIAL | `research_repos/claude-swap/src/claude_swap/switcher.py` (`~533` — the `.unreadable-{epoch}` salvage our adapter cites) | torn-config salvage is a module-level helper, no port/Protocol boundary to put it on |
| ai-usagebar | ABSENT | — | no account-slot file surgery, no headroom-map concept, no capability-seam pattern (Rust `trait`s exist but none carry an uncalled member relevant here) |
| claude-code itself | — | live slot files (`~/.claude.json`, `.credentials.json`) we interoperate with | vendor file semantics only — it has no port surface |

**Count:** 0 of the references implement port-boundary hygiene — it is our own ADR-0010 surface. The salvage *capability* precedent (claude-swap `switcher.py`) already lives in the adapter; M22 only decides the method does not belong on the port.

## Implementation inventory

There is nothing to port — the milestone re-shapes existing boundaries. The files the change touches, grouped by concern:

### AUD-006 — drop `salvage_torn_config` from `ActiveSlotPort`

| Concern | Files |
| --- | --- |
| Port | `src/claude_acc_manager/accounts/application/ports.py` (`~152-158` — the member) |
| Adapter (keeps it) | `src/claude_acc_manager/accounts/infrastructure/active_slot.py` (`~107` definition, `~104` self-call inside `splice_config_oauth_account`) |
| Fake (drop it) | `test/support/fake_active_slot.py` (`~55-57` — uncalled stub; `FailableActiveSlot` inherits, never overrides) |
| Concrete tests (unchanged) | `test/unit/accounts/infrastructure/test_active_slot.py` (4 call sites on the real adapter) |
| Reference only | `src/claude_acc_manager/accounts/infrastructure/unclaimed_store.py` (`~66` pragma comment — still names a real adapter method, no edit) |

### AUD-012 — name the headroom map

| Concern | Files |
| --- | --- |
| Alias home (birth module) | `src/claude_acc_manager/accounts/domain/services/switch_selection.py` (4 sites + `SwitchStrategy` precedent — domain-vocabulary aliases live here) |
| accounts use case | `src/claude_acc_manager/accounts/application/use_cases/switch_account.py` (3 sites) |
| auto domain | `src/claude_acc_manager/auto/domain/services/auto_rank.py` (7 sites), `src/claude_acc_manager/auto/domain/auto_event.py` (`PollEvent.headroom` field) |
| auto application | `src/claude_acc_manager/auto/application/auto_engine.py` (3 sites: `_collect` tuple member + 2 params) |
| tui | `src/claude_acc_manager/tui/app.py` (2 sites: `headroom_map`, `dry_run_best`), `src/claude_acc_manager/tui/autoview.py` (1 site) |
| cli | `src/claude_acc_manager/cli/commands.py` (1 site: `_cached_headroom`) |
| Excluded | `src/claude_acc_manager/tui/account_list.py` `_stamps` — fetched-at stamps, a different concept sharing the bare shape |

Import-linter forces the home: `accounts.domain` cannot import `application`/`infrastructure`; `auto.domain`, `tui`, `cli` all may import `accounts.domain` (precedent: `auto_rank` already imports `usage.domain` + `settings.domain`; `tui`/`cli` import `AccountName`/`SwitchStrategy`). `usage` never imports `accounts` (contract) and never names the map — `account_headroom` returns the scalar.

### AUD-013 — explicit port subclassing

| Concern | Files |
| --- | --- |
| Use cases (3) | `accounts/application/use_cases/status_account.py` → `ActiveIdentityPort` · `usage/application/use_cases/fetch_account_usage.py` → `UsageFetchPort` · `auto/application/use_cases/freshen_target.py` → `FreshenPort` |
| Adapters (2 — same AGENTS.md rule, confirmed in scope at pickup) | `accounts/infrastructure/active_slot.py` → `ActiveSlotPort` · `usage/infrastructure/http_transport.py` → `HttpTransportPort` |
| Port docstrings to reword ("satisfies it structurally" → names the subclass) | `accounts/application/ports.py` (`SwitchExecutorPort`, `ActiveIdentityPort`, `LineageQuarantinePort`) · `usage/application/ports.py` (`UsageFetchPort`) · `auto/application/ports.py` (`FreshenPort`) |
| Already correct (no touch) | `SwitchAccount(SwitchExecutorPort)`, `QuarantineDeadLineage(LineageQuarantinePort)`, all 33 `test/support` fakes, every other infrastructure adapter |

Signatures verified for subclassing: `StatusAccount.execute() -> ActiveAccountStatus | None` matches exactly; `FetchAccountUsage.execute` adds defaults (`force=False`, `threshold=None`) — a legal widening; `FreshenTarget.execute(account_key) -> FreshenStatus` matches exactly.

## Trade-offs and what we adopt

| Axis | Options seen (repo → approach) | Trade-off | Our choice, and why |
| ---- | ------------------------------ | --------- | ------------------- |
| `HeadroomMap` home | `accounts/domain/services/switch_selection.py` (birth module — its docstring defines the map's contract) vs `shared/` vs `usage/domain` | `shared/` would globalize an accounts-owned concept; `usage` is contract-forbidden to `accounts` consumers of the *map* and never names it | `switch_selection.py`, beside `SwitchStrategy` — domain vocabulary lives in the module whose signatures use it |
| `HeadroomMap` shape | `Mapping[str, float | None]` vs `dict[str, float | None]` | `Mapping` covers all 22 sites (17 already `Mapping`; the 5 `dict` sites are construction/field positions where `dict <: Mapping` typechecks) and is the read-most contract | `Mapping` — `PollEvent.headroom` widens to `Mapping` safely (renderers only call `.items()`; callers keep passing `dict`) |
| AUD-013 breadth | the 3 named use cases vs + the 2 structural adapters | the row enumerates use cases but cites AGENTS.md's letter ("subclass the port explicitly") which covers adapters too | all 5 implementers — confirmed at pickup; one convention, one grep result |
| Port docstrings | leave "satisfies it structurally" vs reword | stale wording would contradict the now-explicit code | reword the 5 docstrings to name the implementer, keeping the capability-seam rationale ("the engine depends on the capability, not the use-case class") |

## Gap analysis — what we already have vs the references

| Concern | Ours today (file) | Best reference (file) | Gap |
| ------- | ----------------- | --------------------- | --- |
| Torn-config salvage | `accounts/infrastructure/active_slot.py` — complete, on the adapter and the port | `research_repos/claude-swap/src/claude_swap/switcher.py` `~533` — the naming/0600 precedent | present and complete; the port member itself is dead surface — drop it |
| Headroom map type | bare `Mapping[str, float | None]` repeated 17× + `dict` 5× | none — no reference names this map | present but unnamed — one alias at the birth module |
| Capability-seam subclassing | mixed: 2 use cases subclass, 3 satisfy structurally; 2 adapters structural; 33 fakes all subclass | none — the seam is our ADR-0010 pattern | partial — unify on subclassing per AGENTS.md's letter |

## Deviations

None — the milestone applies the codebase's own stated conventions (AGENTS.md subclassing rule, audit dispositions). No reference-repo behavior is re-shaped.

## Open decisions

None — placement (switch_selection.py), shape (`Mapping`), and AUD-013 breadth (5 implementers) were settled at pickup.

## Surface

| Layer | Files |
| ----- | ----- |
| domain | `accounts/domain/services/switch_selection.py` (alias + 4 sites) · `auto/domain/services/auto_rank.py` (7 sites) · `auto/domain/auto_event.py` (1 site) |
| application (ports / use cases) | `accounts/application/ports.py` (drop member, 3 docstrings) · `accounts/application/use_cases/{switch_account,status_account}.py` · `usage/application/ports.py` + `use_cases/fetch_account_usage.py` · `auto/application/ports.py` + `use_cases/freshen_target.py` + `auto_engine.py` |
| infrastructure | `accounts/infrastructure/active_slot.py` (subclass) · `usage/infrastructure/http_transport.py` (subclass) |
| cli / tui | `cli/commands.py` · `tui/app.py` · `tui/autoview.py` |
| tests | `test/support/fake_active_slot.py` (drop stub); `test/unit/accounts/infrastructure/test_active_slot.py` unchanged (concrete-class tests keep calling the adapter) |

## Tasks

One unit each, one conventional commit each. Mechanical refactors — the green suite is the spec.

- [ ] T1 — `refactor(accounts): drop salvage_torn_config from ActiveSlotPort` — delete the port member (`ports.py ~152-158`) and `FakeActiveSlot.salvage_torn_config` (`fake_active_slot.py ~55-57`); adapter keeps it. Verify: gate green + grep check 1.
- [ ] T2 — `refactor(accounts): name the per-account headroom map HeadroomMap` — `HeadroomMap = Mapping[str, float | None]` + docstring comment in `switch_selection.py`; retype all 22 sites in the inventory's 8 files (`switch_selection` ×4, `switch_account` ×3, `auto_rank` ×7, `auto_engine` ×3, `auto_event` ×1, `tui/app` ×2, `tui/autoview` ×1, `cli/commands` ×1); add `from ...switch_selection import HeadroomMap` where missing. Verify: gate green + grep check 2.
- [ ] T3 — `refactor(ports): implementers subclass their ports explicitly` — `StatusAccount(ActiveIdentityPort)`, `FetchAccountUsage(UsageFetchPort)`, `FreshenTarget(FreshenPort)`, `ActiveSlotAdapter(ActiveSlotPort)`, `UrllibHttpTransport(HttpTransportPort)`; reword the 5 "satisfies it structurally" docstrings. Verify: gate green + grep check 3 — pyright strict catches drift at the class.

## Out of scope

- `tui/account_list.py` `_stamps` — shares the bare `dict[str, float | None]` shape but is a fetched-at-stamp map, not headroom.
- `system_clock`/`palette` basename renames — M23. `poll_policy` fold — M24. File-ceiling splits — M25/M26/M27.
- Any behavior change — every task is a mechanical refactor; the suite must stay green untouched except where a task's own diff demands (none expected — no test asserts the port's member set or the bare shape).
