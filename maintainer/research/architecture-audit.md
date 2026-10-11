# Architecture audit — M21 evidence

Ephemeral (ADR-0001): consumed by M21 and by the fix milestones its findings
spawn. Deleted when the last consumer ships; durable residue lives in code
comments, never here.

Measured 2026-10-11 on commit `bfcf6c6` — re-measure at pickup; treat every
number below as the plan-date snapshot, not truth.

## What the gate already enforces — never re-audited

xenon `--max-absolute B --max-modules B --max-average A` · radon `cc_min A` ·
pyright strict · vulture `>=80` · bandit `-ll` · import-linter contracts
(`pyproject.toml`) · pytest ≥95% branch · mutmut zero disqualifying mutants.

## Audit dimensions

| Dimension | Rule / principle | Measurement method |
| --- | --- | --- |
| File ceiling | ≤500 lines (AGENTS.md, ADR-0010) | `wc -l` per `src/**.py` + `test/**.py` |
| Function length | 4–20 lines (AGENTS.md) | `ast` walk, `end_lineno - lineno` |
| Class size / SRP | one thing per class | method count + responsibility read |
| Port fitness (ISP) | every port method earns its boundary | per-caller usage of each method |
| DIP beyond imports | no `cast`/duck-typing escapes around ports | grep `cast(` at port call sites |
| Duplication | no copy-paste across components | same-basename modules, `diff` |
| Naming | unique concept names (<5 grep hits) | basename + symbol collisions |
| Asymptotic / I/O | no redundant I/O per transaction | count port calls per use-case path |
| Pattern fit | paying patterns only — a pattern must remove more than it adds | read the decision-dense files |
| Primitive obsession | wrapped primitives (calisthenics) | `dict[str, object]` / raw floats through port boundaries |

## Disposition rules (scope decision 2026-10-11)

| Disposition | When | Where it lands |
| --- | --- | --- |
| Fix | the honest change removes more complexity than it adds | a new backlog row — **M21 ships no fixes** |
| Justify | deliberate rule violation | code comment naming the constraint, committed inside M21 |
| Defer | real improvement, wrong time | backlog "Deferred and watched" row |

## Findings ledger — seeds

| ID | Suspect (file) | Snapshot | Question the audit answers |
| --- | --- | --- | --- |
| AUD-001 | `tui/app.py` | 688 lines; `CamApp` 38 methods; `TuiUseCases` protocol 12 methods | God-app vs cohesive screen hub — split nav/menu wiring from app lifecycle? |
| AUD-002 | `auto/application/auto_engine.py` | 549 lines; `AutoEngine` 21 methods; 4 methods rated B (`_tick_inner` 59, `_perform` 38) | Is the engine honest orchestration over `AutoState`+`auto_rank`, or a missed State pattern? |
| AUD-003 | `auto/domain/services/auto_rank.py` | 507 lines; `choose` 65, `rank_candidates` 58, `_admission` 40 | Split at concept boundaries (trigger / no-return / admission) or one dense pure module? |
| AUD-004 | `cli/parser.py` `build_parser` | 155 lines | Declarative argparse table — split by subcommand or justify? |
| AUD-005 | `__main__.py` `build_use_cases` | 75 lines | One composition map is the point of ADR-0013 — justify or split per component? |
| AUD-006 | `accounts/application/ports.py` | 454 lines, 14 ports; `AccountStorePort` 11 methods, `ActiveSlotPort` 9 | ISP pass: a method with a single narrow caller on a fat port is ceremony |
| AUD-007 | `accounts/infrastructure/file_account_store.py` | `_read()` re-parses + revalidates `registry.json` per call; one `SwitchAccount.execute` path triggers ~5–7 reads (`_refuse_scoped_shell`, `_pick`, `_match`, `active` ×2, `quarantined`) + one credential read per account in `_dirs_with_credentials` | Transaction-scoped read vs deliberate lock-free design — which is the honest shape? |
| AUD-008 | `system_clock.py` twins | `accounts/` returns ISO str (`now_iso`), `usage/` returns epoch float (`now_epoch_s`) — same class + port names, different contracts | Rename (`IsoClock`/`EpochClock`) or accept per-component naming? `claude_contract_probe` twins are documented-deliberate — check drift anyway |
| AUD-009 | `palette.py` collision | `shared/palette.py` = severity colors; `tui/palette.py` = Textual command palette | Two concepts, one basename — rename one |
| AUD-010 | Presentation across transports | `tui/formatting.py` 397 lines (bars, rows, reset text) vs `cli/human.py` + `cli/auto_output.py` | How much severity/usage text logic is implemented twice? |
| AUD-011 | `dict[str, object]` credential blobs | flows through `ActiveSlotPort`, `UnclaimedCredentialPort`, `AccountDirPort` | Opaque-by-contract (ADR-0012) or a missing `Credential` value object? |
| AUD-012 | `headroom: Mapping[str, float | None]` | crosses `accounts`/`auto` boundaries | Type alias or fine? |
| AUD-013 | `SwitchAccount` implements `SwitchExecutorPort` | use-case-is-a-port-implementation | Consistent pattern or one-off — do other use cases get consumed through ports the same way? |
| AUD-014 | `fetch_account_usage.execute` | 55 lines; `_resolve_access_token` 35 | Refresh → fetch → persist pipeline decomposition |
| AUD-015 | `usage/domain/services/poll_policy.py` | 410 lines; `plan_after_fetch` 51, `due_candidate` 39 | Pure policy tables or extractable concepts? |
| AUD-016 | `accounts/application/use_cases/collect_doctor_report.py` | `CollectDoctorReport` 9 methods | Verify helpers stay helpers — not a hidden second use case |
| AUD-017 | `test/` (scope includes it) | named fakes in `test/support/` | Overfit tests asserting implementation over contract — they'd block the refactors above |
| AUD-018 | `accounts/domain/services/switch_selection.py` | `select_switch_target` 32, `_rotate` 32 | Confirm the strategy if-tree is minimal — likely fine |

## PRD decisions for SL-022

- Ledger row format and whether `AUD-NNN` ids are final.
- Whether fix findings become sequential milestone rows (`open`, no arrow until picked) or "Deferred and watched" rows — mechanics of the backlog.
- Audit order — suggestion: `shared` → `usage` → `accounts` → `auto` → `settings`+`update` → `cli` → `tui` (dependencies first, transports last).
- Commit type for justification comments (`docs(<component>)` fits convention).
- Gate note: a `refactor` that removes code must keep mutation green — dead branches the audit deletes may carry their own `# pragma: no mutate` cleanup.
