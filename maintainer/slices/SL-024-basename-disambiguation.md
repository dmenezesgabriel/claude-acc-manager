# SL-024 — one name, one concept: the palette and clock twins

Milestone: M23 · State: in-progress · Depends on: SL-023 · Closes: —

> PRD for M23 (AUD-008, AUD-009). Evidence: `maintainer/research/architecture-audit.md` rows AUD-008 and AUD-009. Delete this file when the milestone ships.

## Outcome

Afterwards, `grep -rn "palette\|system_clock" src/` lands each concept on one file: the shared severity ramp is separate from Textual's Command Palette, and the ISO clock adapter is separate from the epoch clock adapter — no two same-named modules carry different contracts.

## Exit gate

`uv run pre-commit run --all-files` clean · full `uv run pytest` green · then the manual validation below. Measurements go in the closing commit's body.

1. `rm -rf mutants` first — renames create new module paths and mutmut's incremental test→function map misses them (ADR-0011).
2. `find src -name 'system_clock.py' -o -name 'palette.py'` returns only `src/claude_acc_manager/tui/palette.py`.
3. `grep -rn "class SystemClock\|shared.palette\|shared/palette" src/ test/ docs/` returns nothing.
4. `uv run pytest -m integration` still imports/collects (no live call needed for the rename) — run only if credentials are present.

## Who else implements this

Internal naming hygiene — no feature is ported. Every reference gets a row so the absence is on record.

| Repo | Has it | Entry points | Approach in one line |
| --- | --- | --- | --- |
| claude-swap | ABSENT | — | no clock/scheduling port abstraction; time is read ad hoc — nothing to mirror |
| ai-usagebar | PARTIAL | `src/theme.rs` | a single `theme` module owns the palette, so it never has two `palette` modules to disambiguate |
| toad | PARTIAL | `toad/src/toad/ansi/_ansi_colors.py` | colors live in one `ansi/_ansi_colors.py`; the name is concept-specific, not a generic `palette` |
| claude-code itself | — | not applicable | naming is internal to this repo; claude-code interoperates only through files and the `claude` binary |

**Count:** 0 of the references implement this refactor. It is not a port — it is the repo's own `AGENTS.md` naming rule (specific, unique names) applied to two collisions the M21 audit found.

## Implementation inventory

No reference repo has a porting inventory (ABSENT/PARTIAL above). The files to open are ours; the collisions are named below.

### AUD-009 — `palette.py` ×2

| Concern | Files |
| --- | --- |
| Shared severity-ramp constants | `src/claude_acc_manager/shared/palette.py` (`ACCENT`, `MUTED`, `WARN_PCT`, `CRIT_PCT`) |
| Textual Command Palette (framework concept — keep the name) | `src/claude_acc_manager/tui/palette.py` |
| Importers of the shared file | `src/claude_acc_manager/cli/human.py:19` (`WARN_PCT`, `CRIT_PCT`) · `src/claude_acc_manager/tui/theme.py:16` (all four) |
| Comment references | `src/claude_acc_manager/cli/human.py:105` · `src/claude_acc_manager/tui/theme.py:14` · `docs/architecture.md:141` |

Decision: `ACCENT`/`MUTED` are used **only** by `tui/theme.py`, so they are not cross-transport — they move next to the other theme colors (`FOREGROUND`, `SEV_OK`, `TRACK`, and their `*_LIGHT` companions) in `src/claude_acc_manager/tui/theme.py`. The shared module then holds exactly the cross-transport severity edges and is named for them.

### AUD-008 — `system_clock.py` ×2 (contract drift under one name)

| Concern | Files |
| --- | --- |
| ISO adapter (`now_iso() -> str`) | `src/claude_acc_manager/accounts/infrastructure/system_clock.py` |
| Epoch adapter (`now_epoch_s() -> float`) | `src/claude_acc_manager/usage/infrastructure/system_clock.py` |
| Composition root | `src/claude_acc_manager/__main__.py:46,115` (accounts) · `:81,123,130,149,171,179` (usage, aliased `UsageSystemClock`) |
| Unit tests | `test/unit/accounts/infrastructure/test_system_clock.py` · `test/unit/usage/infrastructure/test_system_clock.py` |
| Integration test | `test/integration/test_fetch_account_usage_live.py:37,100` |
| Docstring cross-refs | `src/claude_acc_manager/accounts/infrastructure/claude_contract_probe.py:5` · `src/claude_acc_manager/usage/infrastructure/claude_contract_probe.py:5` |
| Durable doc references | `docs/architecture.md:112` (accounts) · `:122` (usage) · `docs/adr/0011:40` (the duplicate `test_system_clock.py` example) |

Decision: rename module **and** class on both sides — `iso_system_clock.py`/`IsoSystemClock`, `epoch_system_clock.py`/`EpochSystemClock` — and mirror the test filenames. That clears the basename collision the milestone is named for, not just the symbol collision. The `claude_contract_probe` twins (identical modulo docstring+import) stay as-is: import-linter forces the per-component adapter, and the audit justified them (no drift).

## Trade-offs and what we adopt

| Axis | Options seen | Trade-off | Our choice, and why |
| ---- | ------------ | --------- | ------------------- |
| Shared ramp name | `severity_ramp.py` (ours) vs `severity_palette.py` vs keep `palette.py` | `severity_ramp` describes the cross-transport concept; keeping `palette` leaves the vaguer word | `severity_ramp.py` — matches the module docstring's own phrase ("one severity ramp") |
| Where `ACCENT`/`MUTED` live | stay shared vs move to `tui/theme.py` | staying puts TUI-only colors in a shared ramp module | move to `tui/theme.py` — every other color constant is already there, and no non-TUI caller exists |
| Clock rename depth | class only vs module + class | class-only leaves the module basename collision | module + class — the milestone is basename disambiguation |

## Gap analysis — what we already have vs the references

| Concern | Ours today (file) | Best reference (file) | Gap |
| ------- | ----------------- | --------------------- | --- |
| One name per concept | `shared/palette.py` vs `tui/palette.py`; two `system_clock.py` | `ai-usagebar/src/theme.rs` (one palette module) · `toad/src/toad/ansi/_ansi_colors.py` (concept-specific name) | present but partial — the constants exist and are correct; only the names collide |
| Cross-transport ramp edges | `shared/palette.py` (`WARN_PCT`/`CRIT_PCT`) | n/a | complete — the rename keeps the single source of truth the CLI and TUI already share |
| Clock contract separation | two `ClockPort` protocols + two adapters | n/a | present but partial — contracts already differ correctly; only the class/module names do not |

## Deviations

None. This is a mechanical rename with two small constant moves; no behavior changes.

## Open decisions

None — both naming decisions were settled with the maintainer before this PRD (see Trade-offs).

## Surface

| Layer | Files |
| ----- | ----- |
| domain | — |
| application (ports / use cases) | — |
| infrastructure | `accounts/infrastructure/iso_system_clock.py` · `usage/infrastructure/epoch_system_clock.py` |
| cli / tui | `shared/severity_ramp.py` · `cli/human.py` · `tui/theme.py` |
| tests | `test/unit/accounts/infrastructure/test_iso_system_clock.py` · `test/unit/usage/infrastructure/test_epoch_system_clock.py` · `test/integration/test_fetch_account_usage_live.py` |

## Tasks

One conventional commit each; renames carry their importers so the gate stays green per commit.

- [ ] T1 — `refactor(shared): name the cross-transport severity ramp` — rename `shared/palette.py` → `shared/severity_ramp.py` (keep `WARN_PCT`/`CRIT_PCT`); move `ACCENT`/`MUTED` into `tui/theme.py`; update `cli/human.py`, `tui/theme.py`, and their comments.
- [ ] T2 — `refactor(accounts): name the ISO clock adapter` — `accounts/infrastructure/system_clock.py` → `iso_system_clock.py`, `SystemClock` → `IsoSystemClock`; update `__main__.py`, the unit test (rename to `test_iso_system_clock.py`), and the `accounts` probe docstring.
- [ ] T3 — `refactor(usage): name the epoch clock adapter` — `usage/infrastructure/system_clock.py` → `epoch_system_clock.py`, `SystemClock` → `EpochSystemClock`; update `__main__.py` (drop the `UsageSystemClock` alias), the unit test (rename to `test_epoch_system_clock.py`), and the integration test.
- [ ] T4 — `docs: repoint the renamed palette and clock modules` — `docs/architecture.md:141,112,122` and the `docs/adr/0011:40` duplicate-module example.

## Out of scope

- Renaming `tui/palette.py` (it names Textual's real Command Palette) or the `claude_contract_probe` twins (justified in AUD-008).
- Any behavioral change to the clocks, the ramp thresholds, or the theme colors.
- Splitting `shared/severity_ramp.py` further — two constants do not need it.
