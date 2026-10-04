# Backlog

**Start here.** This is the entry point for an execution session.

| Need | Read |
| --- | --- |
| What to work on next | this file — the first row marked `open ← next` |
| How to build a milestone | `docs/slices/SL-NNN-*.md`, written when the milestone is picked up, never in advance |
| Why the system is shaped this way | [architecture.md](architecture.md) and [adr/](adr/) |
| Starting a milestone PRD | copy [slices/_TEMPLATE.md](slices/_TEMPLATE.md) |

## Finding things — grep, don't read

Every doc is written to be grepped: ids are unique tokens, facts sit one per table row, paragraphs are not hard-wrapped, file names are written in full.

| To find | Run |
| --- | --- |
| The next milestone | `grep -n "open ← next" docs/backlog.md` |
| One decision | `grep -rn "ADR-0007" docs/` |
| Unchecked tasks in a PRD | `grep -n "\[ \]" docs/slices/*.md` |
| Every doc citing a source file | `grep -rn "anthropic_oauth.py" docs/` |

Id prefixes: `ADR-NNNN` decision · `M<n>` milestone · `SL-NNN` slice PRD · `T<n>` task inside one PRD · `GAP-NNN` parity gap · `R<n>` research session.

## The rules

- Documents are separated by **lifetime**, not topic: `docs/adr/` and `docs/architecture.md` are durable; `docs/research/` and `docs/slices/` are ephemeral ([ADR-0001](adr/0001-split-durable-decisions-from-ephemeral-build-evidence.md)).
- Durable docs and code comments cite real sources of truth — the endpoint's own contract, an upstream issue, a `src/` path — never `research_repos/`. Scaffolding comes down.
- A milestone is `shipped` only after its exit gate is green **and** its manual validation ran. Measurements go in the closing commit's **body**, never here — a row gets one line.
- Correct docs by **editing** them. Git holds the history; no dated correction blocks.
- A milestone's PRD is **written when the milestone is picked up and deleted when it ships**. Anything worth keeping becomes an ADR or a code comment first.
- Finish what is started: no milestone opens while an earlier one is `open` or `partial`.
- `research_repos/` is read-only and untracked: read it for evidence — never install, import, link, vendor, or commit it.

## Milestones

Exit gate for every milestone, no exceptions: `uv run pre-commit run --all-files` clean · full `uv run pytest` green · the row's validation performed · the numbers recorded in the milestone's closing commit body.

| # | Deliverable | Validation | State |
| --- | --- | --- | --- |
| M0 | uv scaffold (py312, `textual` runtime pin, pinned dev toolchain); all tool configs; pre-commit + commit-msg wiring; `path_resolver` (XDG, `CLAUDE_CONFIG_DIR`, `.claude.json` homedir asymmetry) | hooks green on `--all-files`; scratch-`CLAUDE_CONFIG_DIR` probe observed where credentials land | shipped |
| M1 | `shared/fsio` atomic 0600/0700 writes; `entities` + `value_objects`; `FileAccountStore` + registry | modes, rename-atomicity, hermetic tmp-HOME tests | shipped |
| M2 | `active_slot` (credentials, `oauthAccount` splice preserving other keys, torn-file salvage); `claude_locks` (proper-lockfile-compatible mkdir locks, staleness) | fixture-file tests; lock interop vs claude-code's mkdir layout | shipped |
| M3 | `add` (login-at-source via `LoginLauncherPort`), `remove`, `list`, `status`; minimal `cam` CLI + `__main__` composition root | hermetic tests incl. fake launcher; live `add`→`list`→`status`→`remove` round-trip | shipped |
| M4 | `anthropic_oauth`: usage GET, refresh POST, profile GET; injectable transport; host allowlist; token redaction | fake-transport tests (200/401/403/429/`invalid_grant`); redaction + allowlist tests; live-200 smoke (`-m integration`) | shipped |
| M5 | `FetchAccountUsage` (fresh-cache-first, inactive-only refresh, `invalid_grant` signal, 429 backoff + last-good); `headroom`; `poll_policy`; `cache_trust`; `FileUsageCache`; `cam usage` | budget arithmetic ≤ ~30 req/h; cache-state tests; live smoke cached correctly | shipped |
| M6 | `switch_account` transaction (5 steps + rollback); `switch_selection` (`best` / `next-available`); `set_account_enabled`; `cam switch` — closes GAP-001, GAP-002, GAP-003 | failure-injection rollback at each step; strategy edge cases (strictly-greater, unmeasurable current, all-exhausted) | shipped |
| M7 | full CLI surface: `--json` contract, root guard, `enable`/`disable` commands — closes GAP-006 | command tests via isolated HOME; `--json` schema stability | shipped |
| M8 | TUI dashboard + switch + auto view (textual); reads cache; network only via the throttled use case — closes GAP-005 | Textual pilot tests, `TERM=dumb` | shipped |
| M9 | `auto_tick` + `auto` loop (`--once` exit codes incl. 3 blocked, threshold/cooldown/hysteresis, SIGTERM-clean); quarantine persistence; urgent-mode poll policy; `settings.json` + `cam config` — closes GAP-004, GAP-007 | tick-semantics tests; 10-point isolated-HOME manual validation | shipped |
| M10 | claude-version contract gate: band model `[2.1.144, 2.2.0)`, fail-closed with `CAM_ASSUME_CLAUDE_CONTRACT` override; mutating ops gate (add/switch/usage/auto) at the narrowest unsafe op, reads ungated; launcher env sweep | 88-point stub-version matrix (0.2.126–3.0.0) per command + override + no-claude + real-2.1.288 smoke | shipped |
| M11 | TUI ergonomics refactor to textual-8.x idioms (`getters` descriptors, `@work`/`@on`, `data_bind`, `AUTO_FOCUS`, `push_screen_wait`, `PAUSE_GC_ON_SCROLL` + `gc.freeze()`) — zero behavior change | Pilot suite green; `test/` diff = T3 spy-seam moves only; 34-point scripted walkthrough (nav + watch arm/Esc + remove modal + `TERM=dumb`/60-col pty) — evidence: `docs/research/toad-ux.md` | shipped |
| M12 | TUI UX features: F1 help panel + binding groups/tooltips, busy throbber, terminal title + blink, menu key accelerators, `ALLOW_SELECT=False` chrome, `HORIZONTAL_BREAKPOINTS` narrow mode, command palette + provider, settings screen generated from `SETTING_SPECS`, `Visual`/`Strip` bar renderer, `get_loading_widget` | Pilot tests per feature; `TERM=dumb` + ~60-col manual pass — evidence: `docs/research/toad-ux.md` | planned |
| M13 | CLI UX: rich human-output layer (NO_COLOR/non-TTY/`TERM=dumb` fallbacks, `--json` untouched), `--version`, `cam doctor` diagnostics, bare `cam` → TUI (usage fallback when headless), severity-colored auto event lines | command tests incl. color-env and non-TTY matrix + `--json` purity — evidence: `docs/research/toad-ux.md` | planned |

Milestone order rationale: strategies (M6) need measurement (M4/M5); switching needs the store (M1) and the active-slot adapter (M2); everything before M4 is network-free. M11 refactors the surface M12 extends; M13 is CLI-only and sequenced last so the shared presentation lessons from M11/M12 (severity semantics, status-surface conventions) are settled before a second consumer lands.

## Deferred and watched

| Item | Owner | Why deferred |
| --- | --- | --- |
| `extra_usage` (pay-as-you-go credits) parsing | unscheduled | no consumer of spend exists yet — added when one does ([ADR-0012](adr/0012-schema-tolerant-usage-model.md)) |
| Secret Service / dbus credential storage | post-v1 | file storage sits behind `AccountStorePort`/fsio today ([ADR-0003](adr/0003-credentials-at-rest-under-xdg-with-private-modes.md)) |
| systemd unit packaging | non-goal | the foreground `auto` loop is systemd-runnable without our packaging ([ADR-0006](adr/0006-auto-scope-one-shot-and-foreground-loop.md)) |
| macOS/keychain/menubar, Claude Desktop, session merging, directory mappings, aliases, export/import, API-key and setup-token accounts | non-goal | out of v1 scope (architecture §11) |
