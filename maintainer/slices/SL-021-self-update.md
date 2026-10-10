# SL-021 — self-update: release check, notify surfaces, `cam upgrade`

Milestone: M20 · State: open · Depends on: — · Closes: —

> A PRD exists so the executing agent **never guesses and never assumes**. Every `research_repos/` path below was verified with `test -e` on 2026-10-09. Behavioral evidence (what each reference *does*, not just which files) lives in `maintainer/research/self-update.md`.

## Outcome

`cam` tells the user when a newer release exists on PyPI — after CLI commands (stderr, `--json`-clean), on TUI mount (notification), in `cam auto` output (event line) — and `cam upgrade` applies it by delegating to the detected installer (`uv tool upgrade` / `pipx upgrade`), never by self-replacing files.

## Exit gate

`uv run pre-commit run --all-files` clean · full `uv run pytest` green · then the manual validation below, run by a human or scripted against the real tool. Measurements go in the closing commit's body.

1. Fresh shell, `cam config get updates.mode` → `notify`; `cam config set updates.mode off` silences every surface; `CAM_DISABLE_UPDATE_CHECK=1` silences regardless of setting.
2. `cam list --json` byte-identical whether a check fires or not (stdout purity); the notice lands on stderr only.
3. `cam tui` on a real install → notification toast when `pypi.org` reports newer; nothing when equal.
4. `cam upgrade` on the maintainer's uv-tool install performs `uv tool upgrade claude-acc-manager` (dry evidence: a stub-PyPI-ahead state is faked by cache seeding per tasks, live run validated by maintainer).
5. `cam upgrade` in an editable/dev checkout (`0.0.0+local`) and on an unknown install method → prints the manual command list, exit 1.
6. `cam doctor` still passes; settings screen shows the `updates` section row.

Write this PRD to be grepped: do not hard-wrap paragraphs, keep one fact per table row, write file names in full.

## Who else implements this

**Every reference repo gets a row, including the ones that do not have it.**

| Repo | Has it | Entry points | Approach in one line |
| --- | --- | --- | --- |
| opencode (v2 dev, added 2026-10-09 for this PRD) | FULL | `research_repos/opencode/packages/opencode/src/installation/index.ts`, `src/cli/upgrade.ts`, `src/cli/cmd/upgrade.ts` | config `autoupdate: bool\|"notify"` + env kill; fire-and-forget check on TUI boot; per-method registry lookup; semver release-type — **patch auto-installs, minor/major notify**; installer shell-out, never self-replaces |
| claude-swap | FULL | `research_repos/claude-swap/src/claude_swap/update_check.py`, `cli.py` (~1355 upgrade dispatch, ~1482 post-command notice) | PyPI JSON GET, 24h `update_check.json` cache (failures cached), 2s timeout, all-exceptions→None; `sys.prefix` pair-match → `uv`/`pipx`; `cswap upgrade` runs `uv tool upgrade`/`pipx upgrade`, unknown → manual list exit 1; notify-only, no auto-apply |
| ai-usagebar | PARTIAL | `research_repos/ai-usagebar/src/tray/update_flow.rs`, `src/update.rs` | GitHub `releases/latest` → sha256-verify → binary rename dance beside the exe — the *download* model, not the *delegation* model; contributes discipline (prereleases/drafts never offered, HTTPS-only, byte caps, error names status never body) not mechanism |
| toad | ABSENT | — | no self-update machinery found |
| claude-code itself | PARTIAL | vendor behavior: claude-code self-updates in place (npm global / native installer writes its own binary) | not portable — cam is a Python package, not a binary; delegation model applies |

**Count:** 2 of the references implement the check+delegate pattern; 1 implements download+swap (wrong model for a Python package); 1 lacks it. The delegation pattern is proven twice — build it, shaped on claude-swap (same ecosystem) with opencode's policy surface (three-mode setting, patch-only auto).

## Implementation inventory

### opencode

| Concern | Files |
| --- | --- |
| Domain logic | `packages/opencode/src/installation/index.ts` — `getReleaseType` (~24-33 semver major/minor/patch), `Info` schema, `UpgradeFailedError`; `packages/core/src/installation/version.ts` — `InstallationVersion`/`InstallationChannel` ("local" channel = dev build) |
| Ports / boundaries | `packages/opencode/src/installation/index.ts` — `Interface` (~75-80): `info`, `method`, `latest`, `upgrade`; `Schema.Struct` response shapes for every registry (~64-73) |
| Use case / orchestration | `packages/opencode/src/cli/upgrade.ts` — the whole policy in one 53-line fn: config gate → env gate → detect → latest → equal-skip → release-type → patch-install vs minor/major-notify → `OPENCODE_ALWAYS_NOTIFY_UPDATE` test hook |
| Infrastructure adapter | `packages/opencode/src/installation/index.ts` — `method()` execPath heuristics + per-manager `list` probes (~174-207); `latest()` per-method registry queries (~208-264); `upgrade()` subprocess shell-out per method (~265-321); `upgradeCurl` fetches install script over HTTPS then pipes to bash/sh (~145-165) |
| CLI / TUI entry point | `packages/opencode/src/cli/cmd/upgrade.ts` — `upgrade [target] [-m method]`, unknown-method interactive confirm; `packages/opencode/src/cli/tui/worker.ts` (~58-62) `checkUpgrade` fire-and-forget on boot; `packages/opencode/src/cli/cmd/tui.ts` (~266) `client.call("checkUpgrade")` |
| Persistence | none — no check cache (opencode pays one registry GET per boot) |
| Error / edge cases | all swallowed at every layer (`upgrade().catch(() => {})`, transport `.catch`→empty); `unknown` method → no auto-apply ever; `local` channel skips; events `UpdateAvailable`/`Updated` on GlobalBus |
| Config / env | `packages/core/src/config.ts` ~42 — `autoupdate: bool|"notify"` optional; `packages/core/src/flag/flag.ts` ~23-24 — `OPENCODE_DISABLE_AUTOUPDATE`, `OPENCODE_ALWAYS_NOTIFY_UPDATE` |

### claude-swap

| Concern | Files |
| --- | --- |
| Domain logic | `src/claude_swap/update_check.py` — `_parse_version` (~19-20: naive `int.split` — crashes on `1.2.0rc1`, caught by the outer try → silent), `_detect_install_method` (~23-43: `sys.prefix` adjacent-pair match `("uv","tools")`/`("pipx","venvs")`, `UV_TOOL_DIR`/`PIPX_HOME` trusted only when `prefix.is_relative_to(root)`) |
| Ports / boundaries | none — module-level functions, urllib + subprocess direct |
| Use case / orchestration | `update_check.py` — `check_for_update` (~46-89: cache-read → maybe-fetch → compare → method-detect → hint-string) and `run_self_upgrade` (~92-135: detect → argv → subprocess.run → rc) |
| Infrastructure adapter | `update_check.py` — `urllib.request.urlopen(PYPI_URL, timeout=2)`, `subprocess.run(["uv","tool","upgrade",…])`/`["pipx","upgrade",…]` |
| CLI / TUI entry point | `src/claude_swap/cli.py` ~1355-1370 (`--upgrade` dispatch before switcher init), ~1482-1490 (notice on stderr after non-`--json`, non-`--purge`, non-`--upgrade` commands) |
| Persistence | `src/claude_swap/cache.py` — `read_cache(path, ttl)`/`write_cache`, `MISSING` sentinel; `CACHE_DIR/update_check.json`, 24h TTL, **failure value cached too** |
| Error / edge cases | `check_for_update` wraps everything → None; Windows prints the command instead of running it (locked running exe, ~119-125); `FileNotFoundError` (PM absent from PATH) → named error exit 1; `--purge`/`--upgrade`/`--json` skip the check |

### ai-usagebar

| Concern | Files |
| --- | --- |
| Domain logic | `src/update.rs` — pure decisions split from glue: `is_newer`, `parse_release`, `select_downloads`, `parse_sha256_sidecar`, `stage_swap` |
| Use case / orchestration | `src/tray/update_flow.rs` — `check`→`check_at` (~52-84): status non-2xx → error naming status; prerelease/draft → `Ok(None)` not error; `is_newer` gates the offer |
| Infrastructure adapter | `src/tray/update_flow.rs` — reqwest client w/ UA `ai-usagebar-tray/<ver>` (~26), HTTPS-only refusal (~127), content-length cap + post-read cap (~139-156), sha256 sidecar verify before staging (~112-124), `debug_assertions` dev-build refusal (~90) |

## Trade-offs and what we adopt

| Axis | Options seen (repo → approach) | Trade-off | Our choice, and why |
| ---- | ------------------------------ | --------- | ------------------- |
| Auto-apply scope | opencode → patch auto-installs, minor/major notify; claude-swap → never installs | silent `uv tool upgrade` under a running TUI risks a torn venv mid-session; notify-only adds a manual step | Three modes `updates.mode` ∈ `off`/`notify`/`auto`, **default `notify`** (maintainer decision 2026-10-09); `auto` adopts opencode's patch-only rule |
| Check trigger | opencode → TUI boot only; claude-swap → every CLI command end | TUI-only misses pure-CLI users; per-command costs nothing with a cache | Both: post-command stderr notice + TUI-mount worker + `auto` loop event line — one cached probe per 24h |
| Version compare | opencode → `semver` dep; claude-swap → `int.split` (fragile) | no `semver`/`packaging` allowed (ADR-0002 stdlib-only) | Hand-rolled: `^\d+(\.\d+)+$` → int-tuple compare, right-pad zeros; anything else → not-an-update (ai-usagebar's prerelease refusal + dev-build skip via `0.0.0+local`) |
| Failure policy | opencode → swallow all; claude-swap → swallow all + cache the failure; ai-usagebar → name status, drop body | a check that can break the tool is unacceptable; caching failure avoids hammering PyPI offline | claude-swap's: never-raise, cache `None` for the TTL; unlike claude-swap ours writes via `fsio.atomic_write_json` under the store flock discipline |
| Install-method source | opencode → execPath + PM list probes; claude-swap → sys.prefix pairs + env override | PM probes cost subprocesses for a check that should stay cheap | claude-swap's, plus **receipt disambiguation** verified live 2026-10-09: `uv-receipt.toml` `requirements[].specifier` = registry install vs `git`/`path`/`url` = VCS/local (blind `uv tool upgrade` on a git receipt re-pulls HEAD, not the release); pipx via `pipx_metadata.json` `main_package.package_or_url` |
| Check endpoint | opencode → per-method registries; claude-swap → PyPI JSON | per-method registries buy nothing here — PyPI is the single release source (PSR publishes there) | `https://pypi.org/pypi/claude-acc-manager/json` `info.version` — verified live: returns `1.1.0` |
| Upgrade argv | opencode → `npm i -g pkg@ver` pinned; claude-swap → bare `uv tool upgrade pkg` | pinning a target lets `upgrade [target]` exist; bare upgrade always takes latest | `cam upgrade [target]` — bare `uv tool upgrade`/`pipx upgrade` when no target, `pkg==target` form when given (opencode parity for the flag, claude-swap parity for the common path) |

## Gap analysis — what we already have vs the references

| Concern | Ours today (file) | Best reference (file) | Gap |
| ------- | ----------------- | --------------------- | --- |
| Release feed | absent — `usage/infrastructure/anthropic_oauth.py` is Anthropic-allowlisted; `usage/infrastructure/http_transport.py` is a reusable generic urllib transport | `research_repos/claude-swap/src/claude_swap/update_check.py` (`PYPI_URL` GET) | absent — new adapter `update/infrastructure/pypi_release_feed.py` over the existing transport |
| Install-method detection | absent | `research_repos/claude-swap/src/claude_swap/update_check.py` `_detect_install_method` | absent — new pure `update/domain/services/install_method.py` + receipt check |
| Version order | absent | `research_repos/ai-usagebar/src/update.rs` (`is_newer`) | absent — new pure `update/domain/services/version_order.py` |
| Check cache | absent — `usage/infrastructure/file_usage_cache.py` is the schema-fail-loud atomic-write precedent | `research_repos/claude-swap/src/claude_swap/cache.py` `read_cache`/`write_cache` | absent — new `update/infrastructure/file_update_cache.py` |
| Policy surface | `settings/domain/settings_spec.py` choice-kind exists (`autoswitch.strategy`) | `research_repos/opencode/packages/core/src/config.ts` `autoupdate` | partial — spec kind exists; new `updates` section + `updates.mode` + `LoadUpdateSettings` needed |
| Upgrade subprocess | absent | `research_repos/claude-swap/src/claude_swap/update_check.py` `run_self_upgrade` | absent — new port `UpgradeRunnerPort` + `SubprocessUpgradeRunner` + `SelfUpgrade` use case |
| CLI command | `cli/parser.py` subcommand pattern, `cli/dispatch.py` handler dispatch | `research_repos/opencode/packages/opencode/src/cli/cmd/upgrade.ts` | absent — `cam upgrade [target]` parser entry + `cmd_upgrade` |
| Notify surfaces | `cli/human.py` `HumanOutput` (stderr via `out.error`), TUI `app.notify`, `cli/auto_output.py` severity event lines | `research_repos/claude-swap/src/claude_swap/cli.py` ~1482 stderr notice | absent — three hooks, all behind `updates.mode` + `CAM_DISABLE_UPDATE_CHECK` |
| Env kill-switch | `CAM_ASSUME_CLAUDE_CONTRACT` precedent (`shared/claude_contract.py`) | `research_repos/opencode/packages/core/src/flag/flag.ts` `OPENCODE_DISABLE_AUTOUPDATE` | absent — `CAM_DISABLE_UPDATE_CHECK` |
| Dev-build guard | `claude_acc_manager/__init__.py` `package_version()` → `0.0.0+local` for unpacked checkouts | `research_repos/opencode/packages/core/src/installation/version.ts` local channel; `ai-usagebar` `debug_assertions` refusal | present and partial — exists, needs the non-release → skip-check rule wired into `CheckUpdate` |

## Deviations

- **No download-and-swap** (ai-usagebar's model): cam is a Python package with a working package manager on every supported install path; delegating to `uv`/`pipx`/`pip` inherits their atomicity and verification for free.
- **Receipt-aware detection** beyond claude-swap: `uv-receipt.toml`/`pipx_metadata.json` distinguish registry installs from `git+`/local installs — a git-sourced tool gets reinstall guidance instead of a `uv tool upgrade` that re-resolves the ref. Verified against live receipts on this machine 2026-10-09.
- **No receipt → `unknown`** (claude-swap trusts the prefix alone): without the receipt a source install cannot be ruled out, so `cam upgrade` never runs blind. uv source keys are uv's `RequirementSourceWire` variants (`git`/`url`/`path`/`directory`/`editable`/`virtual`); pipx registry = `package_or_url` is the canonical name plus optional extras/specifier, mirroring pipx's own `valid_pypi_name`.
- **No Windows print-only branch**: cam is POSIX-only (`FlockOpsLock`, XDG paths); claude-swap's locked-exe workaround is noted and skipped.
- **`docs/architecture.md` §1 "Local-first — no update checks" row is amended** by this milestone; the statement predates a release channel worth checking and the check stays opt-out (`updates.mode off`, `CAM_DISABLE_UPDATE_CHECK`).
- **Notice goes to stderr always** (never stdout, `--json` or not) — the M7 machine contract's stdout purity is untouched.

## Open decisions

- `cam upgrade` target pinning: `uv tool upgrade` accepts `pkg@ver`? (verify during T4 — `uv tool upgrade --help`; pipx is `pipx upgrade pkg` only, no pin → target arg may be uv-only or dropped if neither supports it cleanly).
- Whether `updates.mode auto` may ever run under `cam auto`'s loop (recommendation: no — loop is unattended, notify only; PRD task records the choice).
- A `cam doctor` row for install-method/latest is deferred to the slice's discretion (cross-component: `CollectDoctorReport` lives in `accounts`).

## Surface

| Layer | Files |
| ----- | ----- |
| domain (services — pure, per AGENTS.md) | `src/claude_acc_manager/update/domain/services/version_order.py`, `update/domain/services/install_method.py` |
| application (ports / use cases) | `update/application/ports.py` (`ReleaseFeedPort`, `UpgradeRunnerPort`, `UpdateCheckCachePort`, `HttpGetPort`), `use_cases/check_update.py`, `use_cases/self_upgrade.py`, `settings/application/use_cases/load_update_settings.py`, `settings/domain/settings_spec.py` (+`updates` section), `settings/application/ports.py` (+`load_updates`) |
| infrastructure | `update/infrastructure/pypi_release_feed.py`, `update/infrastructure/file_update_cache.py`, `update/infrastructure/subprocess_upgrade_runner.py`, `settings/infrastructure/file_settings.py` (+`load_updates`) |
| cli / tui | `cli/parser.py` (+`upgrade` subcommand), `cli/commands.py` (+`cmd_upgrade`), `cli/dispatch.py` (post-command notice), `cli/auto_output.py` (event line), `tui/app.py` (`on_mount` worker → `notify`), `cli/context.py` + `__main__.py` (wiring), `pyproject.toml` (import-linter contracts) |
| tests | `test/unit/update/` tree mirroring src; `test/support/fake_release_feed.py`, `fake_upgrade_runner.py`, `in_memory_update_cache.py`; dispatch + Pilot surface tests |

## Tasks

One TDD unit each, one conventional commit each.

- [x] T1 — `update/domain/services/version_order.py`: `parse_release`/`is_newer`/`release_type` pure; matrix tests (1.9.0≺1.10.0, rc/dev/`+local` → not-an-update, zero-padding, equal)
- [x] T2 — `update/domain/services/install_method.py`: `detect_install_method(prefix, env, receipt)` pure → `uv`|`pipx`|`vcs`|`unknown` (registry-vs-source receipt split is its own `VCS` member — maintainer decision); prefix-pair table + env-override + receipt tests
- [x] T3 — `update/application/ports.py` + `FileUpdateCheckCache` + `PyPiReleaseFeed` + `SubprocessUpgradeRunner`; fake-transport 200/500/garbage tests, atomic-write + drift tests, fakes in `test/support/`
- [ ] T4 — `CheckUpdate` use case: cache-first, failure-cached, never-raises, mode+env gating, `0.0.0+local` skip; `UpdateSettings` + `updates.mode` spec + `LoadUpdateSettings`; `CAM_DISABLE_UPDATE_CHECK`
- [ ] T5 — `SelfUpgrade` + `cam upgrade [target]`: argv per method, unknown/vcs-sourced → manual list exit 1, `FileNotFoundError` → named error
- [ ] T6 — surfaces: dispatch post-command stderr notice (suppression matrix test: `--json`/`upgrade`/`--version`/usage), TUI `on_mount` worker → `notify` (Pilot), `auto` event line
- [ ] T7 — contracts (`update` domain-pure/app-domain-only/infra-ports-only + cli forbidden list) + docs (`docs/reference/cli.md`, `settings.md`, `environment-variables.md`, architecture.md §1 local-first row + §component list)

## Out of scope

- Download-and-install of binaries, sha256 verification, delta updates — the delegation model makes all of it the package manager's job.
- Auto-update of anything but `patch` releases; `minor`/`major` are always notify-only (opencode's rule, adopted).
- Windows support — cam is POSIX-only today.
- A `cam doctor` update-info row — discretionary, noted in Open decisions.
- Release-channel machinery (`beta`/`nightly` tracks) — PSR publishes stable only; the schema-tolerant compare already refuses prerelease offers.
