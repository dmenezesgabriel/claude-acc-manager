# SL-022 — Architecture audit: disposition every finding the gate cannot see

Milestone: M21 · State: in-progress · Depends on: — · Closes: —

## Outcome

Every structural suspect in `src/` + `test/` carries a measured verdict and a landed disposition — a new backlog row for honest fixes, a committed code comment for deliberate violations, a "Deferred and watched" row for real-but-untimely improvements — with zero behavior change shipped inside the milestone.

## Exit gate

`uv run pre-commit run --all-files` clean · full `uv run pytest` green · then the manual validation below, run by a human or scripted. Measurements go in the closing commit's body.

1. `grep -c "|.*|.*|" maintainer/research/architecture-audit.md` — every AUD-NNN row in the findings ledger has a non-empty `Verdict` and `Lands where` cell (`clean`, `fix`, `justify`, or `defer`).
2. Every file over the 500-line ceiling in `src/` and `test/` appears in the ledger: re-run `find src test -name '*.py' | xargs wc -l | awk '$1>500'` and check each path off against the AUD rows (grouped rows naming a set of paths are fine).
3. `git log --oneline` over the milestone range contains only `docs(` and `chore(` types — zero `feat`/`fix`/`refactor`/`perf` commits.
4. For every `fix` verdict there is a matching `open` row in the backlog Milestones table; for every `defer` verdict a row under "Deferred and watched"; for every `justify` verdict the cited `src/` comment exists (`grep` the path the row names).
5. `maintainer/research/architecture-audit.md` survives the milestone (its header already declares it dies with the last consuming fix milestone, not this one).

## Who else implements this

**Every reference repo gets a row, including the ones that do not have it** — an absence is evidence too. This milestone audits our code against *our own* rules (AGENTS.md ceilings, ADR-0010 package-by-component, ISP/DIP/SRP); no reference repo supplies an audit methodology to port.

| Repo | Has it | Entry points | Approach in one line |
| --- | --- | --- | --- |
| claude-swap | ABSENT | `research_repos/claude-swap/src/claude_swap/switcher.py` (7,431 lines in one file), `research_repos/claude-swap/tests/test_switcher.py` (12,488) | No ceilings, god-module structure — negative evidence: its monolith is the shape our component split exists to prevent |
| ai-usagebar | ABSENT | `research_repos/ai-usagebar/src/config.rs` (4,392 lines), `research_repos/ai-usagebar/CLAUDE.md` | No file ceilings — **but** CLAUDE.md codifies architecture invariants as *guard tests* ("a guard test forbids a second caller of `Cache::fallback_payload`"), a technique fix milestones spawned here may adopt |
| toad | ABSENT | `research_repos/toad/src/toad/widgets/conversation.py` (1,948 lines) | No audit/ceiling convention visible — negative evidence only |
| claude-code itself | — | — | Vendor behavior only; nothing to interoperate with for an internal audit |

**Count:** 0 of the references run an architecture audit or enforce structural ceilings. This milestone is *conformance* — our code measured against our own documented rules — plus pattern-fit reads where a reference is a known exemplar (already consumed by earlier milestones; nothing new is ported).

## Implementation inventory

No repo is FULL/PARTIAL, so the inventory is the audit's own reading list — the decision-dense files each finding opens. Measured at HEAD `01188ea` on 2026-10-11 (re-verified this session; the seed snapshot at `bfcf6c6` matches on every spot-checked number).

| Concern (audit dimension) | Files to open |
| --- | --- |
| File ceiling — `src/` over 500 | `src/claude_acc_manager/tui/app.py` (688), `src/claude_acc_manager/auto/application/auto_engine.py` (549), `src/claude_acc_manager/auto/domain/services/auto_rank.py` (507) |
| File ceiling — `test/` over 500 | `test/unit/test_cli.py` (4,343), `test/unit/auto/domain/services/test_auto_rank.py` (1,433), `test/unit/usage/application/use_cases/test_fetch_account_usage.py` (1,155), `test/unit/accounts/application/use_cases/test_switch_account.py` (1,054), `test/unit/auto/application/test_auto_engine.py` (965), `test/unit/accounts/infrastructure/test_file_account_store.py` (891), `test/unit/tui/test_widgets.py` (889), `test/unit/usage/domain/services/test_poll_policy.py` (711), `test/unit/tui/test_app.py` (588), `test/unit/accounts/infrastructure/test_active_slot.py` (557), `test/unit/usage/infrastructure/test_anthropic_oauth.py` (522), `test/unit/tui/test_visuals.py` (507) |
| Function length — `src/` worst offenders (of 105 functions >20 lines) | `src/claude_acc_manager/cli/parser.py` `build_parser` (155), `src/claude_acc_manager/__main__.py` `build_use_cases` (75), `src/claude_acc_manager/auto/domain/services/auto_rank.py` `choose` (65) / `rank_candidates` (58), `src/claude_acc_manager/auto/application/auto_engine.py` `_tick_inner` (59) / `_perform` (38), `src/claude_acc_manager/usage/application/use_cases/fetch_account_usage.py` `execute` (55), `src/claude_acc_manager/usage/domain/services/poll_policy.py` `plan_after_fetch` (51) |
| Function length — `test/` (173 functions >20) | `test/support/engine_harness.py`, `test/support/use_cases.py`, `test/support/tui_app.py`, `test/unit/test_cli.py` — audit as a *grouped* finding (see Deviations) |
| Port fitness (ISP) | `src/claude_acc_manager/accounts/application/ports.py` (14 Protocols, 454 lines: `AccountStorePort` 11 methods, `ActiveSlotPort` 9) — map every method to its callers |
| I/O multiplicity per transaction | `src/claude_acc_manager/accounts/infrastructure/file_account_store.py` (`_read()` re-validates per call) × `src/claude_acc_manager/accounts/application/use_cases/switch_account.py` (8 injected ports, 36 `self._<port>.` call sites in `execute`/`_transact`) |
| Basename collisions / naming | `src/claude_acc_manager/accounts/infrastructure/system_clock.py` (`now_iso` → str) vs `src/claude_acc_manager/usage/infrastructure/system_clock.py` (`now_epoch_s` → float); `src/claude_acc_manager/shared/palette.py` (severity colors) vs `src/claude_acc_manager/tui/palette.py` (command palette); `src/claude_acc_manager/accounts/infrastructure/claude_contract_probe.py` vs `src/claude_acc_manager/usage/infrastructure/claude_contract_probe.py` (documented-deliberate twins — diff for drift) |
| Pattern fit / surface size | `src/claude_acc_manager/tui/app.py` (`CamApp` 38 methods, `TuiUseCases` protocol 12), `src/claude_acc_manager/auto/application/auto_engine.py` (`AutoEngine` 21 methods), `src/claude_acc_manager/accounts/application/use_cases/collect_doctor_report.py` (`CollectDoctorReport` 9), `src/claude_acc_manager/usage/domain/services/poll_policy.py` (410) |
| Primitive obsession | `dict[str, object]` through `ActiveSlotPort`/`UnclaimedCredentialPort`/`AccountDirPort` (93 occurrences across src — see `src/claude_acc_manager/accounts/application/ports.py`); `headroom: Mapping[str, float | None]` crossing `accounts`/`auto`/`tui`/`cli` (`src/claude_acc_manager/accounts/domain/services/switch_selection.py`, `src/claude_acc_manager/auto/domain/auto_event.py`) |
| Use-case-as-port-implementation | `src/claude_acc_manager/accounts/application/use_cases/switch_account.py` (`SwitchAccount(SwitchExecutorPort)`), `src/claude_acc_manager/accounts/application/use_cases/quarantine_dead_lineage.py` (`QuarantineDeadLineage(LineageQuarantinePort)`), `src/claude_acc_manager/accounts/application/use_cases/status_account.py` (implements `ActiveIdentityPort` **without subclassing** — convention break vs AGENTS.md "subclass the port explicitly"), `src/claude_acc_manager/auto/application/auto_engine.py` (consumes `ActiveIdentityPort`) |
| Presentation duplicated across transports | `src/claude_acc_manager/tui/formatting.py` (397: bars, rows, reset text) vs `src/claude_acc_manager/cli/human.py` + `src/claude_acc_manager/cli/auto_output.py` |
| DIP beyond imports | every `cast(` call site (all carry `# pragma: no mutate` notes today — verify each guards a proven shape, e.g. `src/claude_acc_manager/accounts/domain/credential_fields.py`, `src/claude_acc_manager/accounts/domain/oauth_identity.py`, `src/claude_acc_manager/cli/commands.py`) |
| Test double quality | `test/support/` (`engine_harness.py`, `use_cases.py`, `tui_app.py`, `fake_diagnostics.py`) — overfit tests asserting implementation over contract would block the fix rows this audit spawns |

## Trade-offs and what we adopt

| Axis | Options seen | Trade-off | Our choice, and why |
| ---- | ------------ | --------- | ------------------- |
| Where `fix` findings land | Milestones table (`open`, no arrow) vs "Deferred and watched" | Milestone rows are committed work and get picked up in order; deferred rows are unscheduled parking | **Milestones table** — the ledger's own disposition rules say "a new backlog row"; honest fixes we intend to ship are milestones, not wishes |
| `test/` ceiling treatment | Same rules as src / exempt tests entirely / grouped finding | 12 files × per-file rows would bury the ledger; exempting tests hides a 4,343-line file | **Grouped finding** — one AUD row per *class* of test-ceiling violation (harness/support vs unit files); dispositions still per the same rules |
| Function-length rule on test bodies | Enforce 4–20 on tests / treat per-file | AAA test bodies legitimately run long; the rule's letter says "functions" without carving out tests | Audit **per-file** — the file ceiling is the enforceable rule on `test/`; a test function >20 lines only becomes a finding when it signals a missing fake/helper (judged in T8) |
| Basename duplicates | All same-name files are collisions / convention files are exempt | `ports.py` ×5 and `__init__.py` ×N are the ADR-0010 per-component convention, not collisions | **Exempt convention names** (`__init__.py`, `ports.py`, `types.py`); audit only semantic twins (`system_clock`, `palette`, `claude_contract_probe`) |

## Gap analysis — what we already have vs the rules

| Concern | Ours today | Best reference | Gap |
| ------- | ---------- | -------------- | --- |
| File ceilings | 3 `src/` + 12 `test/` files over 500 | none (references are worse) | present and partial — ceilings documented, not enforced by the gate |
| Port subclassing | `StatusAccount` consumes `ActiveIdentityPort` without subclassing | `FileAccountStore(AccountStorePort)` et al. | present and partial — convention held by 20+ adapters, broken by one use case |
| `cast(` discipline | every site pragma-justified | — | complete, pending per-site verification |
| Architecture-invariant guard tests | absent — nothing fails the build when a rule like "one caller of X" breaks | ai-usagebar `CLAUDE.md` guard-test idiom | absent — candidate technique for spawned fix milestones, not for M21 itself |

## Deviations

- **`__init__.py`, `ports.py`, `types.py` same-name files are convention, not collisions** — ADR-0010 requires per-component `application/ports.py`; auditing them as name clashes is noise. Stated here so T2–T8 don't churn.
- **No refactors in M21** — a `fix` verdict produces a backlog row, never a code change. Justify-comments are the only `src/` edits permitted inside the milestone.
- **Gate note for spawned fixes, not this milestone** — a future refactor that removes code must keep mutation green; dead branches deleted then may carry their own `# pragma: no mutate` cleanup. Recorded so the fix PRDs remember.

## Open decisions

None — the five decisions the seed ledger deferred to this PRD are settled in "Trade-offs and what we adopt" above (ledger row format: append `Verdict` + `Lands where` columns; AUD-NNN ids final; fix → `open` milestone row; audit order per tasks; justify-comments commit `docs(<component>)`).

## Surface

| Layer | Files |
| ----- | ----- |
| domain | justification comments only, where verdicts land `justify` |
| application (ports / use cases) | justification comments only |
| infrastructure | justification comments only |
| cli / tui | justification comments only |
| tests | none — overfit-test findings become backlog rows |
| maintainer | `maintainer/research/architecture-audit.md` (evidence + verdicts), `maintainer/backlog.md` (new rows, M21 → shipped) |

## Tasks

One unit each, one conventional commit each — `docs(maintainer)` for ledger work, `docs(<component>)` for justify-comments, `docs(backlog)` for row edits.

- [ ] T1 — Re-run every measurement at HEAD (file ceilings, function lengths, class method counts, `cast(` census, basename diff, `dict[str, object]` census, `SwitchAccount.execute` port-call count); refresh any stale seed numbers in `maintainer/research/architecture-audit.md`; append AUD-019+ rows for the 12 test-file ceiling violations, the `test/` >20-line function group, and the `StatusAccount` non-subclassing finding.
- [ ] T2 — Audit `shared/` + `settings/` + `update/`: disposition their findings (`palette.py` collision share, `install_method` casts, `headroom` alias at the accounts/auto seam as it lands here). Fill `Verdict`/`Lands where`; land any justify-comments.
- [ ] T3 — Audit `usage/`: `poll_policy.py` (410, `plan_after_fetch` 51, `due_candidate` 39), `fetch_account_usage.execute` (55) + `_resolve_access_token` (35), `system_clock` twin contract (`now_epoch_s`), `claude_contract_probe` twin drift check.
- [ ] T4 — Audit `accounts/`: `ports.py` ISP pass (every method of `AccountStorePort`/`ActiveSlotPort` mapped to callers), `file_account_store._read()` re-validation per port call, `dict[str, object]` blobs vs ADR-0012/ADR-0014, `system_clock` twin (`now_iso`), use-case-as-port consistency (`SwitchAccount`, `QuarantineDeadLineage`, `StatusAccount`), `switch_selection` if-tree minimalism, `collect_doctor_report` helper boundary.
- [ ] T5 — Audit `auto/`: `AutoEngine` 21-method surface + `_tick_inner`/`_perform` decomposition honesty (orchestration vs missed State pattern), `auto_rank` concept boundaries (trigger / no-return / admission), `headroom` type-alias question closed.
- [ ] T6 — Audit `cli/`: `build_parser` 155 (declarative-table split vs justify), `build_use_cases` 75 (ADR-0013 composition-map justification), `json_output`/`human`/`auto_output` duplication vs `tui/formatting.py` share (joint verdict with T7), `commands.py` cast.
- [ ] T7 — Audit `tui/`: `app.py` 688/`CamApp` 38-method split question, `TuiUseCases` 12-method protocol fitness, `palette.py` rename verdict, `formatting.py` vs cli duplication verdict (with T6).
- [ ] T8 — Audit `test/`: the 12 file-ceiling findings + `test/support/` fake quality (overfit checks asserting implementation over contract) + the grouped test-function-length finding.
- [ ] T9 — Disposition sweep: write every `fix` verdict as an `open` row in the Milestones table, every `defer` as a "Deferred and watched" row, verify every `justify` comment exists in tree; ledger has zero unresolved rows.
- [ ] T10 — Closeout: exit-gate validation §1–§5 above, M21 row → `shipped`, delete this PRD, numbers in the closing commit body.

## Out of scope

- **All refactoring** — file splits, renames, port slimming, `Credential` value object, test-file decomposition: each is a `fix` verdict's new backlog row, owned by its own future milestone.
- **Gate-visible axes** — xenon/radon/pyright/vulture/bandit/import-linter/coverage/mutation are already enforced; the audit never re-checks them (seed ledger, "What the gate already enforces").
- **New features or behavior changes** — prohibited by the milestone row itself.
- **`research_repos/` mutations** — read-only per ADR-0001; the guard-test idiom is cited as a technique, not imported.
