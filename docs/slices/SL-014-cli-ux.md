# SL-014 — CLI UX: styled human output, --version, doctor, bare cam → TUI

Milestone: M13 · State: open · Depends on: SL-013 (severity semantics, status surfaces) · Closes: —

## Outcome

Human-facing `cam` output is styled (severity colors, accent chrome) and degrades cleanly under `NO_COLOR`, pipes, and `TERM=dumb`; `cam --version` prints the package version; `cam doctor` renders a diagnostics report; bare `cam` opens the TUI when interactive and keeps usage+2 when it is not. `--json` payloads are untouched byte-for-byte.

## Exit gate

`uv run pre-commit run --all-files` clean · full `uv run pytest` green · then the manual validation below, run by a human or scripted against the real tool. Measurements go in the closing commit's body.

1. `cam --version` prints `cam X.Y.Z`, exits 0.
2. `cam list` / `cam status` / `cam usage <name>` / `cam config list` in a real color terminal show styled output; `cam list | cat`, `NO_COLOR=1 cam list`, and `TERM=dumb cam list` emit byte-identical text with zero ANSI.
3. `cam list --json | cat` and `cam auto --once --json` are unchanged schema-v1 bytes (no ANSI ever reaches stdout under `--json`).
4. `cam doctor` on the live box renders all sections and exits 0 even while reporting an out-of-band or absent claude.
5. Bare `cam` in a pty opens the TUI dashboard; `cam | cat` and `TERM=dumb cam` print usage to stderr and exit 2. `cam tui` unchanged.
6. `cam auto --once` in a color terminal shows severity-colored event lines.

## Who else implements this

**Every reference repo gets a row, including the ones that do not have it** — an absence is evidence too, and a capability present in none is an invention and must be justified.

| Repo | Has it | Entry points | Approach in one line |
| --- | --- | --- | --- |
| toad (v0.6.20, Python) | FULL — the pattern source | `research_repos/toad/src/toad/cli.py`, `research_repos/toad/src/toad/about.py`, `research_repos/toad/src/toad/app.py` (`run_on_exit`) | rich `Console`/`print` for human output, `DefaultCommandGroup` injects the default subcommand, `about` renders a markdown env/paths/versions report, `-v/--version` flag |
| claude-swap (v0.27.0b1, Python) | PARTIAL — same UX goals, hand-rolled | `research_repos/claude-swap/src/claude_swap/printer.py`, `research_repos/claude-swap/src/claude_swap/appearance.py`, `research_repos/claude-swap/src/claude_swap/cli.py` | hand-rolled ANSI + `colors_enabled()` (NO_COLOR/FORCE_COLOR/TTY/TERM=dumb), dark/light palettes via OSC-11 background probe + `ui.theme` setting, `action="version"`, bare-invocation→TUI TTY gate |
| ai-usagebar (v1.14.0, Rust) | PARTIAL — diagnostics + sanitize discipline | `research_repos/ai-usagebar/src/detect.rs`, `research_repos/ai-usagebar/src/display.rs`, `research_repos/ai-usagebar/src/bin/ai-usagebar.rs` | `detect [--all] [--json]` diagnostics command (exit 0 on a produced report, 1 only when the probe/serialize fails), untrusted text sanitized at the sink, clap `--version` |
| claude-code itself (vendor behavior we must interoperate with) | — | `/doctor` diagnostics UI inside its own surface; nothing to mirror on our CLI | No shared-file or process contract is touched by this milestone — interop stays ADR-0015's version gate |

**Count:** 3 of the references implement some of this; none implements all of it. The combination is conventional CLI surface (version flag, styled output, a doctor command, default-to-TUI) — every piece has a precedent in at least one reference.

## Implementation inventory

### toad

| Concern | Files |
| --- | --- |
| Default subcommand | `research_repos/toad/src/toad/cli.py` (`DefaultCommandGroup.parse_args`, ~line 56) |
| Diagnostics report | `research_repos/toad/src/toad/about.py` (`ABOUT_TEMPLATE` sections: config, paths, system, dependencies, env) |
| `--version` | `research_repos/toad/src/toad/cli.py` (`-v/--version` flag on the group) |
| rich human print | `research_repos/toad/src/toad/cli.py` (`from rich import print`), `research_repos/toad/src/toad/app.py` (`run_on_exit` panel) |
| Post-TUI recap | `research_repos/toad/src/toad/app.py` + `cli.py` (`app.run_on_exit()`) — not adopted, see Out of scope |

### claude-swap

| Concern | Files |
| --- | --- |
| ANSI output layer | `research_repos/claude-swap/src/claude_swap/printer.py` (`colors_enabled`, `_detect_color_support`, `force_color`, stylers, `error`/`warning`) |
| Theme detection machinery | `research_repos/claude-swap/src/claude_swap/appearance.py` (`detect_terminal_background` OSC-11 query, `resolve_theme`, `cli_should_probe`, `cli_theme`) — we do NOT adopt this; see Trade-offs |
| `--version` | `research_repos/claude-swap/src/claude_swap/cli.py` (~line 1089, `action="version"`) |
| Bare → TUI gate | `research_repos/claude-swap/src/claude_swap/cli.py` (~line 1024, `if not argv and sys.stdout.isatty() and sys.stdin.isatty(): argv = ["--tui"]`) |

### ai-usagebar

| Concern | Files |
| --- | --- |
| Diagnostics command | `research_repos/ai-usagebar/src/detect.rs` (`run_cli` ~line 296, `format_report` ~line 326) |
| Untrusted-text sink | `research_repos/ai-usagebar/src/display.rs` (`sanitize_untrusted_{line,path}`) |
| `--version` | `research_repos/ai-usagebar/src/bin/ai-usagebar.rs` (clap builtin; parse before any state validation) |

## Trade-offs and what we adopt

| Axis | Options seen (repo → approach) | Trade-off | Our choice, and why |
| ---- | ------------------------------ | --------- | ------------------- |
| Output layer | toad → rich `Console`; claude-swap → hand-rolled ANSI `printer.py` | rich wraps/ellipsizes/markup-parses; ANSI is zero-dep but weaker and already rejected in R1 | rich — `rich>=14.2,<16` is a declared runtime dep (`pyproject.toml`); `Console` natively honors NO_COLOR/FORCE_COLOR/TERM=dumb/non-TTY (verified in `.venv`'s rich — `is_dumb_terminal`, `_detect_color_system`) |
| Markup safety | toad → markup strings; ai-usagebar → sanitize at the sink | Account names, emails, and error messages are untrusted text containing arbitrary `[` `]` — rich markup would eat or mangle them | `HumanOutput` accepts `Text`/renderables and escapes at construction; no `console.print("[tag]")` markup anywhere in `cli/` |
| Severity colors | claude-swap → standard ANSI red/yellow in BOTH palettes; only accent/muted are palette-keyed via OSC-11 + `ui.theme` | Reusing the TUI's hex ramp assumes a dark terminal — `SEV_WARN #d7af5f` is near-invisible on light backgrounds; building claude-swap's probe machinery for a CLI has no payoff | Named ANSI severities (`green`/`yellow`/`red`) + `bold`/`dim` structure — theme-adaptive, zero config. `ACCENT`/`MUTED` hexes + `WARN_PCT`/`CRIT_PCT` edges move to `shared/palette.py` so both transports share severity *semantics* |
| Lazy imports | ours → `tui/__init__.py` keeps textual/rich out of `--json` paths; toad → lazy screen factories | Eager `import rich` in `cli/` costs every `cam list --json` (cron path) | `HumanOutput` builds its `Console` on first human print — `--json` handlers never trigger the import |
| `doctor` exit code | ai-usagebar `detect` → 0 on any produced report, 1 only when the probe/serialization itself fails; toad `about` → 0 | Gating findings into the exit code exists in no reference; the contract refusal already lives in every mutating op — doctor's job is to *show* it | Exit 0 whenever the report renders; nonzero only when the diagnostic itself cannot run. Unsupported contract renders as a FAIL row |
| `doctor --json` | ai-usagebar `detect --json` exists — for frontend consumers | No cam consumer of doctor JSON exists (same "added when a consumer exists" rule that deferred `extra_usage`) | Deferred — the `DoctorReport` model keeps it additive. Stated in Out of scope |
| `--version` | claude-swap → `action="version"` (`SystemExit`); ai-usagebar → clap builtin parsed before state | `SystemExit` out of `run()` breaks its "always returns int" contract and is awkward under the mutation gate | `--version` store_true flag handled inside `run()` → print + return 0, before the root guard (same class as `--help`) |
| Version source | claude-swap → hardcoded `__version__`; ours → `pyproject.toml` `version` | Two version literals drift | `importlib.metadata.version("claude-acc-manager")` exposed as `claude_acc_manager.__version__`; `PackageNotFoundError` → `"0.0.0+local"` |
| Bare → TUI gate | claude-swap → `not argv and stdin.isatty() and stdout.isatty()` | Probing `sys` inside `dispatch` breaks hermeticity | `ProcessContext.interactive: bool = False`, probed in `__main__` (`stdin`+`stdout` TTY and `TERM not in ("dumb","unknown")` — TERM=dumb falls back per the R1 decision); dispatch maps bare `cam` → `cmd_tui` when interactive, else usage+2; the root guard then applies uniformly |
| Report assembly | toad `about.py` → template over app facts | `cli/` cannot import `path_resolver`/`shared` probes (import-linter: use cases and ports only) | `DiagnosticsPort` (accounts boundary — it owns the claude interop facts) + `OsDiagnosticsProbe` adapter (env/home/store_root injected) + `CollectDoctorReport` use case; `cmd_doctor` only renders |

## Gap analysis — what we already have vs the references

| Concern | Ours today (file) | Best reference (file) | Gap |
| ------- | ----------------- | --------------------- | --- |
| Human CLI output | `print()` throughout `src/claude_acc_manager/cli/commands.py`, `dispatch.py` | toad `cli.py`/`about.py` rich prints | absent — no styling layer |
| Markup-safe sink | none needed today (plain print) | ai-usagebar `display.rs` | absent — needed the moment rich enters |
| Version flag | none | claude-swap `action="version"` | absent |
| Diagnostics | none | toad `about.py`, ai-usagebar `detect.rs` | absent — `cam doctor` |
| Default command | `handler is None` → usage+2 (`cli/dispatch.py`) | claude-swap bare→TUI TTY gate, toad `DefaultCommandGroup` | absent |
| Auto event styling | plain `{stamp}  {line}` (`commands.py` `_auto_emit`) | claude-swap severity colors, toad severity pills | absent |
| Severity ramp source | `tui/theme.py` `SEV_*`/`WARN_PCT`/`CRIT_PCT` (textual import — cli cannot touch it) | claude-swap shared palette | present but unreachable from cli — constants move to `shared/` |

## Deviations

- No OSC-11 background probe, no `ui.theme` setting: claude-swap's machinery exists to key accent/muted per terminal theme; named ANSI severities make it unnecessary here. If a light-terminal complaint ever lands, the seam is `shared/palette.py`, not a detector.
- `--version` handled as a flag inside `run()`, not `action="version"` — keeps `run()`'s int contract; stated here so the argparse-idiomatic shortcut isn't "simplified" back in a later edit.
- `cam doctor` has no `--json` — deferred until a consumer exists; the `DoctorReport` DTO is serializable by construction so the flag is additive.
- No `run_on_exit` recap (toad's post-TUI panel): the switch outcome already surfaces inside the TUI via toasts.

## Open decisions

None — every question the references disagree on is settled in Trade-offs with evidence cited.

## Surface

| Layer | Files |
| ----- | ----- |
| domain | `accounts/application/doctor_report.py` (`DoctorReport`, `DoctorCheck` — port-adjacent DTOs, `ActiveAccountStatus` precedent) |
| application (ports / use cases) | `accounts/application/ports.py` (`DiagnosticsPort`), `accounts/application/use_cases/collect_doctor_report.py` (`CollectDoctorReport`) |
| infrastructure | `accounts/infrastructure/diagnostics_probe.py` (`OsDiagnosticsProbe`) |
| shared | `shared/palette.py` (severity edges + accent/muted constants moved from `tui/theme.py`) |
| cli / tui | `cli/human.py` (`HumanOutput`), `cli/parser.py` (`--version`, `doctor`), `cli/dispatch.py` (bare→TUI, version handling, `out` plumbing), `cli/commands.py` (+ `cli/auto_output.py` when the auto block crosses the 500 ceiling), `cli/context.py` (`ProcessContext.interactive`, `UseCases.diagnostics`), `__main__.py` (probe + wiring), `claude_acc_manager/__init__.py` (`__version__`), `tui/theme.py` (imports shared constants) |
| tests | `test/unit/test_cli.py` (version, bare-cam, color matrix, doctor), `test/unit/test_main.py` (interactive probe wiring), `test/unit/accounts/...` (probe adapter, use case), `test/support/fake_diagnostics.py`, `test/support/use_cases.py` |

## Tasks

One TDD unit each, one conventional commit each.

- [ ] T1 — `feat(cli): cam --version` — `claude_acc_manager.__version__` via `importlib.metadata` (`PackageNotFoundError` → `"0.0.0+local"`); root-parser `--version` handled in `run()` → `cam X.Y.Z` on stdout, exit 0, before the root guard.
- [ ] T2 — `feat(cli): bare cam opens the TUI when interactive` — `ProcessContext.interactive` (default False); `__main__` probes stdin+stdout TTY and `TERM`; `run()` maps a handler-less parse to `cmd_tui` when interactive (root guard applies after, as for `cam tui`), else keeps usage+2.
- [ ] T3 — `refactor(cli): HumanOutput seam` — `cli/human.py` (lazy `Console`, markup-free, `highlight=False`, `soft_wrap=True`; `print`/`error`/`severity_style`/`event_style`); `run(..., console=None)`; handlers become `(args, use_cases, out)`; all `print()` calls route through `out` — wording unchanged, existing pins stay green.
- [ ] T4 — `refactor(shared): one severity ramp` — move `WARN_PCT`/`CRIT_PCT`/`ACCENT`/`MUTED` to `shared/palette.py`; `tui/theme.py` imports them. Zero behavior change.
- [ ] T5 — `feat(cli): severity-colored auto event lines` — event-kind→style map (`switch`→green, `error`/`all-exhausted`→red, `account-quarantined`→yellow, `sleep`/`no-switch`→dim, `poll`→plain with the used-pct ramp) + styled banner; extract the auto render block to `cli/auto_output.py` if `commands.py` crosses 500; `--json` JSONL byte-identical.
- [ ] T6 — `feat(cli): style pass on human output` — active `*` accent, `[disabled]`/`[quarantined]` styled, `cam usage` pct ramp, `error:`→stderr red, confirmations bold; wording preserved.
- [ ] T7 — `feat(accounts): cam doctor` — `DoctorReport`/`DoctorCheck` DTOs, `DiagnosticsPort`, `OsDiagnosticsProbe`, `CollectDoctorReport`, `UseCases.diagnostics` + `make_use_cases`/`FakeDiagnostics`, `__main__` wiring, `cmd_doctor` render (cam / claude contract / paths / locks / env / terminal / system), exit 0 on findings.
- [ ] T8 — `docs(readme): CLI UX rows` — `cam doctor`, `--version`, bare `cam` in the commands table.

## Out of scope

- `cam doctor --json` — no consumer (deferred like `extra_usage`); additive later.
- Terminal-background detection / a `ui.theme` CLI setting — named ANSI severities make it unnecessary (see Trade-offs).
- `run_on_exit` post-TUI recap — the switch outcome already surfaces via toasts.
- Re-wording any existing line — styling only; pinned strings remain the interface.
- TUI-side changes — the TUI is finished at M12; M13 touches only the CLI transport and the shared palette move.
