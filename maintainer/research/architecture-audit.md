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
| AUD-001 | `tui/app.py` | 688 lines; `CamApp` 38 methods — all ≤21 lines, thin app-level chrome grouped in stanza-blocks; `TuiUseCases` 12 methods is the uniform-surface Protocol (clean) | God-app vs cohesive screen hub — split nav/menu wiring from app lifecycle? | fix | split at the action-runner seam: `_run_action`/`_action_blocking`/`_action_done` + `do_*` block (~150–200 lines) moves to a collaborator; blocked by AUD-017's ~28 private-access test sites — new milestone row owns both |
| AUD-002 | `auto/application/auto_engine.py` | 549 lines; `AutoEngine` 21 methods; linear tick pipeline with clean section banners — orchestration over `auto_rank`+`AutoState`, not a missed State pattern (a tick is evaluate-once, not behavioral state) | Is the engine honest orchestration, or a missed State pattern? | fix | extract the `-- collection --` stage (~230 lines, 9 methods: `_collect`/`_escalate_all`/`_plan`/`_snapshots`/`_fetch_errors`/`_stale_candidate_plan`/`_reset_parked`/`_eligible_candidates`/`_emit_poll`) into a collaborator — new milestone row |
| AUD-003 | `auto/domain/services/auto_rank.py` | 507 lines; `choose` 65, `rank_candidates` 58, `_admission` 40; ranking signatures carry 11–14 positional params called twice with identical lists | Split at concept boundaries or one dense pure module? | fix | parameter-object for the ranking/admission signatures (the repeated `trigger, candidates, snapshots, headroom, active, active_headroom, threshold, hysteresis_pct, strategy, now_s` list); concept-boundary split is that milestone's call — new milestone row |
| AUD-004 | `cli/parser.py` `build_parser` | 155 lines; zero logic — 16 uniform `add_parser`/`add_argument`/`set_defaults` stanzas | Declarative argparse table — split by subcommand or justify? | justify | docstring added: flat stanza-per-command is deliberate (surface greppable in one file; a spec-table adds a schema for cosmetic gain) — `docs(cli)` |
| AUD-005 | `__main__.py` `build_use_cases` | 75 lines; flat constructor-call map over every use case | One composition map is the point of ADR-0013 — justify or split per component? | justify | docstring added: one flat map is what ADR-0013 exists to consolidate — `docs(cli)` |
| AUD-006 | `accounts/application/ports.py` | 454 lines, 14 ports; every `AccountStorePort`/`ActiveSlotPort` method has ≥1 caller; 6/11 store methods are single-caller but that's the uniform-surface convention (AGENTS.md); one dead member: `ActiveSlotPort.salvage_torn_config` — zero port-side consumers (adapter self-call + concrete-class tests only) | ISP pass: a single narrow caller on a fat port is ceremony | fix | drop `salvage_torn_config` from `ActiveSlotPort` (adapter keeps it as implementation detail); joins the port-hygiene milestone row |
| AUD-007 | `accounts/infrastructure/file_account_store.py` | `_read()` re-parses + revalidates `registry.json` per call; one switch path reads the registry ~4–5× + N credential reads — atomic writes make lock-free reads safe; parse cost is µs on a small file | Transaction-scoped read vs deliberate lock-free design? | justify | comment added on `_read()`: fresh-parse-per-call is the cross-process consistency model — `docs(accounts)` |
| AUD-008 | `system_clock.py` twins | `accounts/` returns ISO str (`now_iso`), `usage/` returns epoch float (`now_epoch_s`) — same class + port names, different contracts; `claude_contract_probe` twins are identical modulo docstring+import (import-linter forces per-component adapters) — no drift | Rename (`IsoClock`/`EpochClock`) or accept per-component naming? | fix (clock rename) + justify (probe twin) | clock: joins the AUD-009 basename-rename milestone row — `IsoSystemClock`/`EpochSystemClock` disambiguate; probe: usage file already cites the constraint, add the symmetric note to `accounts/infrastructure/claude_contract_probe.py` — `docs(accounts)` comment |
| AUD-009 | `palette.py` collision | `shared/palette.py` = severity-color constants (15 lines; imported by `cli/human.py`, `tui/theme.py`); `tui/palette.py` = Textual command palette — the framework's own name for the concept (imported by `tui/app.py`, `test_palette.py`) | Two concepts, one basename — rename one | fix | new milestone row — rename `shared/palette.py` (vaguer name; `tui/` side names a real Textual concept); mechanics in that milestone's PRD |
| AUD-010 | Presentation across transports | `tui/formatting.py` 397 vs `cli/human.py` 157 + `cli/auto_output.py` 189 — shared substrate already extracted (`shared/palette` ramp, `SERVE_TTL_S`/`TRUST_MAX_AGE_S`, `LoadPrivacySettings`); email redaction diverges by contract (CLI omits, TUI masks); `_iso`/`_stamp`/`clock_stamp` differ in format+TZ deliberately | How much severity/usage text logic is implemented twice? | clean | each transport owns its shape; what looks like overlap is contract-level divergence, not copy-paste |
| AUD-011 | `dict[str, object]` credential blobs | 93 occurrences across src; flows through `ActiveSlotPort`, `UnclaimedCredentialPort`, `AccountDirPort`; field access already confined to domain parsers (`credential_fields`, `oauth_identity`) | Opaque-by-contract or a missing `Credential` value object? | justify | docstring added on `ActiveSlotPort`: blobs stay opaque — claude owns the schema (same tolerance posture as ADR-0012), the move model must round-trip arbitrary keys — `docs(accounts)` |
| AUD-012 | `headroom: Mapping[str, float | None]` | crosses `accounts` (`switch_selection.py`, `switch_account.py`), `auto` (`auto_event.py`), `tui` (`app.py`, `autoview.py`), `cli` (`commands.py`) — ~10 signature sites repeating the bare shape | Type alias or fine? | fix | named alias at the birth component (`accounts`) — names the per-account headroom-map concept; joins the port-hygiene milestone row |
| AUD-013 | Use cases as port implementations | Pattern is deliberate: `FreshenPort`'s docstring declares the capability seam ("the engine depends on the capability, not the use-case class"); implementers are inconsistent — `SwitchAccount`/`QuarantineDeadLineage` subclass, `StatusAccount`/`FetchAccountUsage`/`FreshenTarget` satisfy structurally, while all 33 `test/support` fakes subclass | Consistent pattern or one-off? | fix | unify on explicit subclassing (AGENTS.md's letter — grep the port name, land on the implementer; pyright catches drift at the class, not the call site); joins the port-hygiene milestone row |
| AUD-014 | `fetch_account_usage.execute` | 55 lines; `_resolve_access_token` 35 | Refresh → fetch → persist pipeline decomposition | clean | already staged: `_serve_without_fetch`/`_resolve_access_token`/`_handle_fetch_failure`/`_plan_success` named helpers; execute's length is `UsageReport` literal verbosity on three early returns, not logic sprawl |
| AUD-015 | `usage/domain/services/poll_policy.py` | 410 lines; ~107 lines are the documented constants table ("every number in one place" — the module's stated intent); `plan_after_fetch` 51 is mostly contract docstring over ~14 logic lines | Pure policy tables or extractable concepts? | fix | one real duplication: `limiting_reset_epoch`/`earliest_future_reset_epoch`/`earliest_reset_epoch` triplicate the same walk+filter+compare — including the pragma-annotated tie-handling comment ×3 — into one shared fold; new milestone row |
| AUD-016 | `accounts/application/use_cases/collect_doctor_report.py` | `CollectDoctorReport` 9 methods: `execute` + 7 static `_<section>` builders + helpers, all projecting one `DoctorReport` | Verify helpers stay helpers — not a hidden second use case | clean | a section table, not surface sprawl — every private method builds one named section of the same report type |
| AUD-017 | `test/` (scope includes it) | 33 named fakes in `test/support/` — every one subclasses its port explicitly (exemplary); ~28 private-method accesses concentrated in `test/unit/tui/` (`_update_refresh_status`, `_blink_terminal_title`, `_action_done`, `_apply_snapshot`…) | Overfit tests asserting implementation over contract? | fix | the TUI private-access sites would block AUD-001's split — the split milestone owns the rework (assert observable state or bless the seam); the rest of the suite tests at port boundaries — clean |
| AUD-018 | `accounts/domain/services/switch_selection.py` | `select_switch_target` 32, `_rotate` 32; strategy dispatch → `_select_best`/`_rotate`, shared `_ineligible_reason`/`_eligible_others`/`_best_among` helpers | Confirm the strategy if-tree is minimal — likely fine | clean | confirmed minimal — safety contract documented in the module header, decomposition already at the right grain |
| AUD-019 | `test/unit/test_cli.py` | 4,343 lines — 8.7× the file ceiling; ~50 test methods >20 lines; a flat per-command suite, no layering that would block a split | Split by command area, or is one CLI mega-suite deliberate? | fix | split per command area (the suite is already organized by command — the seam exists); joins the test-decomposition milestone row |
| AUD-020 | `test/` file-ceiling group | 11 more files >500: `test_auto_rank` 1,433 · `test_fetch_account_usage` 1,155 · `test_switch_account` 1,054 · `test_auto_engine` 965 · `test_file_account_store` 891 · `test_widgets` 889 · `test_poll_policy` 711 · `test_app` 588 · `test_active_slot` 557 · `test_anthropic_oauth` 522 · `test_visuals` 507 | Per-module split mirroring src, or long suites accepted for tests? | fix | the 500 ceiling applies to `test/` too (AGENTS.md is unqualified); splits mirror the src modules they cover — joins the test-decomposition milestone row |
| AUD-021 | `test/` function-length group | 173 test functions >20 lines; the four worst are composition maps (`make_use_cases` 85, `wired_app` 83 — same flat-wiring shape as `build_use_cases`, AUD-005) or fact tables (`fake_diagnostics.facts` 42); test-method length is AAA verbosity | Missing helper/fake extraction, or acceptable AAA bodies? | clean | wiring maps and arrange-heavy AAA bodies hold up under the per-file reading; the file ceiling (AUD-019/020) is the enforceable rule on `test/` |

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
- **accounts/ (T4, 2026-10-11):** `SwitchAccount`'s 8 injected ports each map
  a distinct resource (registry/live slot/account dirs/unclaimed/claude
  locks/ops lock/clock/contract probe — ADR-0014's lock model needs the two
  lock ports separately); the use case is decomposed into named stages
  (`_capture`/`_pick`/`_require_target`/`_retire_outgoing`/`_rollback`).
  `switch_message.py`, `identity_match.py`, `oauth_identity.py`,
  `credential_fields.py` — small single-purpose domain helpers — clean.
- **auto/ (T5, 2026-10-11):** `loop_delay.py`, `freshen_target.py`,
  `file_auto_state.py`, `auto_state.py`, `auto_event.py` — all ≤128 lines,
  single-purpose — clean. `FreshenPort`'s docstring is the canonical
  statement of the capability-seam pattern AUD-013 audits.
- **cli/ (T6, 2026-10-11):** `dispatch.py` 157 / `commands.py` 487 /
  `json_output.py` 318 — under ceiling; `json_output` is schema payloads
  (data-shaped), `cmd_auto` 37 is event-emission wiring — clean. The lazy
  `from claude_acc_manager.tui import run` inside `commands.py` keeps
  textual out of the headless import graph — deliberate.
- **tui/ (T7, 2026-10-11):** `formatting.py` 397 is a renderer toolkit whose
  module docstring justifies the custom bars (severity ramp + threshold tick
  + stale dimming beat `ProgressBar`); `palette.py`/`theme.py`/`visuals.py`
  each own one concern. `tui/palette.py` names Textual's Command Palette —
  the collision is with `shared/palette.py`, not this file.
- **test/ (T8, 2026-10-11):** `test/support/` is the fakes exemplar the
  convention describes — 33 named fakes, every one subclassing its port,
  all ≤86 lines (`use_cases.py`/`tui_app.py`/`engine_harness.py` are the
  composition helpers, wiring-map shaped). File ceilings are the finding
  here (AUD-019/020), plus the TUI private-access cluster (AUD-017).

## Decisions settled by SL-022 (2026-10-11)

- `AUD-NNN` ids are final; the ledger table carries `Verdict` + `Lands where` columns.
- `fix` findings become `open` rows in the backlog Milestones table (no `← next` arrow — they queue behind whatever is open); `defer` findings become "Deferred and watched" rows.
- Audit order: `shared` → `usage` → `accounts` → `auto` → `settings`+`update` → `cli` → `tui` → `test/` (dependencies first, transports last).
- Justification comments commit as `docs(<component>)`; ledger work as `docs(maintainer)`; backlog rows as `docs(backlog)`.
- Basename convention files (`__init__.py`, `ports.py`, `types.py`) are exempt from collision findings — ADR-0010 requires them per component.
- Gate note for spawned fix milestones: a `refactor` that removes code must keep mutation green — dead branches the fix deletes may carry their own `# pragma: no mutate` cleanup.
