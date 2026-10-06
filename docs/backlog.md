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
| M11 | TUI ergonomics refactor to textual-8.x idioms (`getters` descriptors, `@work`/`@on`, `data_bind`, `AUTO_FOCUS`, `push_screen_wait`, `PAUSE_GC_ON_SCROLL` + `gc.freeze()`) — zero behavior change | Pilot suite green; `test/` diff = T3 spy-seam moves only; 34-point scripted walkthrough (nav + watch arm/Esc + remove modal + `TERM=dumb`/60-col pty) | shipped |
| M12 | TUI UX features: F1 help panel + binding groups/tooltips, busy throbber, terminal title + blink, menu key accelerators, `ALLOW_SELECT=False` chrome, `HORIZONTAL_BREAKPOINTS` narrow mode, command palette + provider, settings screen generated from `SETTING_SPECS`, `Visual`/`Strip` bar renderer, `get_loading_widget` | Pilot tests per feature; `TERM=dumb` + ~60-col manual pass | shipped |
| M13 | CLI UX: rich human-output layer (NO_COLOR/non-TTY/`TERM=dumb` fallbacks, `--json` untouched), `--version`, `cam doctor` diagnostics, bare `cam` → TUI (usage fallback when headless), severity-colored auto event lines | command tests incl. color-env and non-TTY matrix + `--json` purity | shipped |
| M14 | CI + supply-chain gate: `.github/workflows/` (first CI — none exists) — `gate` job running `pre-commit run --all-files` on push/PR under `UV_LOCKED=1`; `uv lock --check` freshness; `pip-audit`; `gitleaks` secret scan (no license on personal repos); `zizmor` `pedantic` workflow lint (SARIF exits 0 — blocking mode is a PRD decision); CodeQL SAST; OpenSSF Scorecard (public-repo gate); `dependabot.yml` (`uv` + `github-actions` ecosystems — keeps SHA pins fresh); every action SHA-pinned; `permissions: {}` top-level, `persist-credentials: false`, `concurrency` + `timeout-minutes` per job — evidence: `docs/research/ci-supply-chain.md` | workflow green on a PR; each scanner runs and reports zero findings; a deliberately-failing commit proves the gate blocks | open — remaining tasks gated on the visibility flip |
| M15 | Docs standardization pass: physical split — `docs/` keeps only publishable content (`architecture.md` + `adr/` today, user pages at M17), `backlog.md`/`slices/`/`research/` move to `dev/` and every `docs/{backlog,slices,research}` reference repoints; `architecture.md` conformed to arc42 §1–§12 (§7 Deployment + §12 Glossary absent; §1 stakeholder/requirements audit) or deviation recorded; `adr/0000-template.md` vs upstream MADR decided then all ADRs re-audited; `prompt-execution.md` → `.agents/skills/next-task/SKILL.md` with `triggers: [user]` (human-only `/next-task`; sanitize the personal path); GitHub community-health files (CONTRIBUTING.md + SECURITY.md minimum — CoC/templates/CODEOWNERS/FUNDING are PRD decisions); fluff + grep-density audit — evidence: `docs/research/docs-standardization.md` | `dev/` holds all process machinery, `docs/` holds none; `/next-task` skill triggers manually only; every docs file maps to a named convention; gate green | open ← next |
| M16 | Workflow restructure to reference grade: per-concern files (`ci` = gate+matrix; `security` = pip-audit·zizmor·gitleaks·codeql; `scorecard` stays); shared checkout+setup-uv+`uv sync` extracted to a `.github/actions/` composite or `workflow_call`; actionlint in the local gate; concurrency reworked so main pushes never cancel in-flight main runs; job `name:`↔ruleset coupling documented — evidence: `docs/research/ci-workflow-conventions.md` | zizmor pedantic + actionlint clean on every workflow; two consecutive main pushes both complete; T11 ruleset check names still resolve | planned |
| M17 | User docs site on GitHub Pages: `mkdocs.yml` (Material — plain config stays Zensical-migratable) at root; `docs/` is already pure site post-M15 — add Diátaxis-shaped user pages (getting-started, guides, reference, internals incl. `architecture.md` + `adr/` nav'd) while machinery stays in `dev/`; deploy via `configure-pages`/`upload-pages-artifact`/`deploy-pages` (`pages: write`+`id-token` on the deploy job only) — deploy leg gated on public visibility — evidence: `docs/research/docs-site.md` | `mkdocs build --strict` green in CI; site serves at `<owner>.github.io/claude-acc-manager`; `dev/` never enters the build | planned |
| M18 | PyPI release pipeline: `python-semantic-release` on `main` (conventional-commit semver bump of `pyproject version` via `version_toml`, generated `CHANGELOG.md`, `v{version}` tag, GitHub release via `publish-action`; `build_command` relocks `uv.lock` via `uv lock --upgrade-package "$PACKAGE_NAME"`) → `uv build` → separate `deploy` job (only job holding `id-token: write`, `environment: pypi` with required reviewer per PyPA) via `pypa/gh-action-pypi-publish` trusted publishing + PEP 740 attestations (default-on) — evidence: `docs/research/release-pipeline.md` | `uv build` + `twine check` clean; `psr --noop` dry-run; TestPyPI proof via `repository-url`; post-publish `pipx install claude-acc-manager==<v>` smoke | planned |

Milestone order rationale: strategies (M6) need measurement (M4/M5); switching needs the store (M1) and the active-slot adapter (M2); everything before M4 is network-free. M11 refactors the surface M12 extends; M13 is CLI-only and sequenced last so the shared presentation lessons from M11/M12 (severity semantics, status-surface conventions) are settled before a second consumer lands. M14 stands up CI and the supply-chain battery first — release (M18) gates on it; both ship after every v1 feature so the first automated release packages the finished surface. M15–M17 were inserted by maintainer order ahead of M14's closeout: all three harden what a public repo exposes, so they land before the visibility flip that M14's remaining tasks (public-run validation, required-check ruleset) and M17's Pages deploy wait on.

## Deferred and watched

| Item | Owner | Why deferred |
| --- | --- | --- |
| `extra_usage` (pay-as-you-go credits) parsing | unscheduled | no consumer of spend exists yet — added when one does ([ADR-0012](adr/0012-schema-tolerant-usage-model.md)) |
| Secret Service / dbus credential storage | post-v1 | file storage sits behind `AccountStorePort`/fsio today ([ADR-0003](adr/0003-credentials-at-rest-under-xdg-with-private-modes.md)) |
| systemd unit packaging | non-goal | the foreground `auto` loop is systemd-runnable without our packaging ([ADR-0006](adr/0006-auto-scope-one-shot-and-foreground-loop.md)) |
| macOS/keychain/menubar, Claude Desktop, session merging, directory mappings, aliases, export/import, API-key and setup-token accounts | non-goal | out of v1 scope (architecture §11) |
