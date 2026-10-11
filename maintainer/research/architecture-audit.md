# Architecture audit — M21 evidence

Ephemeral (ADR-0001): consumed by M21 and by the fix milestones its findings
spawn. Deleted when the last consumer ships; durable residue lives in code
comments, never here.

Snapshot taken 2026-10-11 at `bfcf6c6`; re-measured at pickup on `6a95d23`
(code identical — only docs commits between). Numbers below are the
re-measured values; where the seed and re-measurement differed, the seed
was corrected in place.

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
| Clean | measured and held up | recorded here, nothing lands |

Verdict vocabulary: `clean` · `fix` · `justify` · `defer` (SL-022 PRD).

## Findings ledger

| ID | Suspect (file) | Evidence (re-measured) | Question the audit answers | Verdict | Lands where |
| --- | --- | --- | --- | --- | --- |
| AUD-001 | `tui/app.py` | 688 lines; `CamApp` 38 methods; `TuiUseCases` protocol 12 methods | God-app vs cohesive screen hub — split nav/menu wiring from app lifecycle? | | |
| AUD-002 | `auto/application/auto_engine.py` | 549 lines; `AutoEngine` 21 methods; `_tick_inner` 59, `_perform` 38, `__init__` 35 | Is the engine honest orchestration over `AutoState`+`auto_rank`, or a missed State pattern? | | |
| AUD-003 | `auto/domain/services/auto_rank.py` | 507 lines; `choose` 65, `rank_candidates` 58, `_admission` 40 | Split at concept boundaries (trigger / no-return / admission) or one dense pure module? | | |
| AUD-004 | `cli/parser.py` `build_parser` | 155 lines | Declarative argparse table — split by subcommand or justify? | | |
| AUD-005 | `__main__.py` `build_use_cases` | 75 lines | One composition map is the point of ADR-0013 — justify or split per component? | | |
| AUD-006 | `accounts/application/ports.py` | 454 lines, 14 ports; `AccountStorePort` 11 methods, `ActiveSlotPort` 9 | ISP pass: a method with a single narrow caller on a fat port is ceremony | | |
| AUD-007 | `accounts/infrastructure/file_account_store.py` | `_read()` re-parses + revalidates `registry.json` per call; `SwitchAccount` holds 8 ports and makes 15 `_store.` calls per execute path — one switch can trigger ~15 registry parses, not the seed's ~5–7 | Transaction-scoped read vs deliberate lock-free design — which is the honest shape? | | |
| AUD-008 | `system_clock.py` twins | `accounts/` returns ISO str (`now_iso`), `usage/` returns epoch float (`now_epoch_s`) — same class + port names, different contracts; `claude_contract_probe` twins are identical modulo docstring+import (import-linter forces per-component adapters) — no drift | Rename (`IsoClock`/`EpochClock`) or accept per-component naming? | fix (clock rename) + justify (probe twin) | clock: joins the AUD-009 basename-rename milestone row — `IsoSystemClock`/`EpochSystemClock` disambiguate; probe: usage file already cites the constraint, add the symmetric note to `accounts/infrastructure/claude_contract_probe.py` — `docs(accounts)` comment |
| AUD-009 | `palette.py` collision | `shared/palette.py` = severity-color constants (15 lines; imported by `cli/human.py`, `tui/theme.py`); `tui/palette.py` = Textual command palette — the framework's own name for the concept (imported by `tui/app.py`, `test_palette.py`) | Two concepts, one basename — rename one | fix | new milestone row — rename `shared/palette.py` (vaguer name; `tui/` side names a real Textual concept); mechanics in that milestone's PRD |
| AUD-010 | Presentation across transports | `tui/formatting.py` 397 lines (bars, rows, reset text) vs `cli/human.py` + `cli/auto_output.py` | How much severity/usage text logic is implemented twice? | | |
| AUD-011 | `dict[str, object]` credential blobs | 93 occurrences across src; flows through `ActiveSlotPort`, `UnclaimedCredentialPort`, `AccountDirPort` | Opaque-by-contract (ADR-0012/ADR-0014) or a missing `Credential` value object? | | |
| AUD-012 | `headroom: Mapping[str, float | None]` | crosses `accounts` (`switch_selection.py`, `switch_account.py`), `auto` (`auto_event.py`), `tui` (`app.py`, `autoview.py`), `cli` (`commands.py`) | Type alias or fine? | | |
| AUD-013 | Use cases as port implementations | `SwitchAccount(SwitchExecutorPort)` and `QuarantineDeadLineage(LineageQuarantinePort)` subclass explicitly; `StatusAccount` implements `ActiveIdentityPort` **without subclassing** — convention break (AGENTS.md: "subclass the port explicitly") | Consistent pattern or one-off — and the non-subclassing gap is real either way | | |
| AUD-014 | `fetch_account_usage.execute` | 55 lines; `_resolve_access_token` 35 | Refresh → fetch → persist pipeline decomposition | clean | already staged: `_serve_without_fetch`/`_resolve_access_token`/`_handle_fetch_failure`/`_plan_success` named helpers; execute's length is `UsageReport` literal verbosity on three early returns, not logic sprawl |
| AUD-015 | `usage/domain/services/poll_policy.py` | 410 lines; ~107 lines are the documented constants table ("every number in one place" — the module's stated intent); `plan_after_fetch` 51 is mostly contract docstring over ~14 logic lines | Pure policy tables or extractable concepts? | fix | one real duplication: `limiting_reset_epoch`/`earliest_future_reset_epoch`/`earliest_reset_epoch` triplicate the same walk+filter+compare — including the pragma-annotated tie-handling comment ×3 — into one shared fold; new milestone row |
| AUD-016 | `accounts/application/use_cases/collect_doctor_report.py` | `CollectDoctorReport` 9 methods | Verify helpers stay helpers — not a hidden second use case | | |
| AUD-017 | `test/` (scope includes it) | named fakes in `test/support/` (`use_cases.py`, `tui_app.py`, `engine_harness.py`, `fake_diagnostics.py`) | Overfit tests asserting implementation over contract — they'd block the refactors above | | |
| AUD-018 | `accounts/domain/services/switch_selection.py` | `select_switch_target` 32, `_rotate` 32 | Confirm the strategy if-tree is minimal — likely fine | | |
| AUD-019 | `test/unit/test_cli.py` | 4,343 lines — 8.7× the file ceiling; ~50 test methods >20 lines | Split by command area into per-command suites, or is one CLI mega-suite deliberate? | | |
| AUD-020 | `test/` file-ceiling group | 11 more files >500: `test_auto_rank` 1,433 · `test_fetch_account_usage` 1,155 · `test_switch_account` 1,054 · `test_auto_engine` 965 · `test_file_account_store` 891 · `test_widgets` 889 · `test_poll_policy` 711 · `test_app` 588 · `test_active_slot` 557 · `test_anthropic_oauth` 522 · `test_visuals` 507 | Per-module split mirroring src, or long suites accepted for tests? | | |
| AUD-021 | `test/` function-length group | 173 test functions >20 lines; worst in `test/support/`: `use_cases.make_use_cases` 85, `tui_app.wired_app` 83, `engine_harness.__init__` 49, `fake_diagnostics.facts` 42 | Missing helper/fake extraction, or acceptable AAA bodies? (PRD deviation: per-file rule on test/, judged here) | | |

## Component sweep notes

Per-component evidence for findings that never needed an AUD row — what was
measured and why it held up.

- **shared/ + settings/ + update/ (T2, 2026-10-11):** all files ≤362 lines
  (`settings_spec.py` 362 is the SETTINGS spec table — data, not logic).
  `claude_contract.py` fns at 40/34/22 lines are message-text-heavy decision
  units (band classifier + probe + override glue); splitting adds indirection
  for no coupling win — clean. `install_method.py` casts guard shapes proven
  by `isinstance` or by the `_field` dict-walk contract — clean.
  `update/application/ports.py` is the ISP exemplar: 4 single-purpose ports,
  `HttpGetPort(HttpTransportPort)` narrowing documented inline.
  `shared/container.py`, `fsio.py`, `file_lock.py` — small single-purpose
  adapters — clean.
- **usage/ (T3, 2026-10-11):** `application/ports.py` is the second ISP
  exemplar — 9 single-/two-method ports + value types + error types, every
  boundary earning its name. `pace.compute_pace` (40) and the residual
  >20-line fns (`recent_429` 25, `relevant_windows` 29, `_entry_from_json` 22,
  `request` 24, `__init__` 26) are guard→compute→literal pipelines whose
  length is docstring/signature weight — clean.

## Decisions settled by SL-022 (2026-10-11)

- `AUD-NNN` ids are final; the ledger table carries `Verdict` + `Lands where` columns.
- `fix` findings become `open` rows in the backlog Milestones table (no `← next` arrow — they queue behind whatever is open); `defer` findings become "Deferred and watched" rows.
- Audit order: `shared` → `usage` → `accounts` → `auto` → `settings`+`update` → `cli` → `tui` → `test/` (dependencies first, transports last).
- Justification comments commit as `docs(<component>)`; ledger work as `docs(maintainer)`; backlog rows as `docs(backlog)`.
- Basename convention files (`__init__.py`, `ports.py`, `types.py`) are exempt from collision findings — ADR-0010 requires them per component.
- Gate note for spawned fix milestones: a `refactor` that removes code must keep mutation green — dead branches the fix deletes may carry their own `# pragma: no mutate` cleanup.
