# R: self-update parity evidence — opencode · claude-swap · ai-usagebar

Session: 2026-10-09. Purpose: M20/SL-021 (self-update). Every `research_repos/` path verified with `test -e` this session; `research_repos/` is read-only and never cited from durable docs or code (ADR-0001) — this file is the citation's ephemeral home.

## opencode (cloned 2026-10-09, `sst/opencode` dev)

| Fact | Source |
| --- | --- |
| `autoupdate: bool \| "notify"`, optional — default (unset) auto-installs | `packages/core/src/config.ts` ~42; `packages/core/src/v1/config/config.ts` ~64 |
| `OPENCODE_DISABLE_AUTOUPDATE` + `OPENCODE_ALWAYS_NOTIFY_UPDATE` env flags | `packages/core/src/flag/flag.ts` ~23-24 |
| Version + channel compiled in; `"local"` channel = dev build | `packages/core/src/installation/version.ts` |
| The whole auto policy is one 53-line fn: config gate → env gate → `method()` → `latest(method)` → equal-skip → `getReleaseType` → **patch installs, minor/major emit event** | `packages/opencode/src/cli/upgrade.ts` ~8-53 |
| Check fires once per TUI boot, fire-and-forget, every error swallowed | `packages/opencode/src/cli/tui/worker.ts` ~58-62; `cli/cmd/tui.ts` ~266 `client.call("checkUpgrade")` |
| `method()`: `process.execPath` contains `.opencode/bin` or `.local/bin` → `curl`; else per-manager `list` probes ordered by exec-path name match | `packages/opencode/src/installation/index.ts` ~174-207 |
| `latest(method)` queries the registry *matching the method*: brew API, npm dist-tag, choco OData, scoop bucket JSON, GitHub releases fallback | `packages/opencode/src/installation/index.ts` ~208-264 |
| `upgrade(method, target)` shells per method: `npm/pnpm/bun install -g opencode-ai@<t>`, `brew upgrade`, `choco upgrade --version=`, `scoop install @`, curl fetches `opencode.ai/install` then pipes to bash/sh — **the process never edits its own files** | `packages/opencode/src/installation/index.ts` ~145-165, ~265-321 |
| `upgrade [target] [-m method]` manual command; `unknown` method → interactive "Install anyways?" confirm; same-version → warn + skip | `packages/opencode/src/cli/cmd/upgrade.ts` ~23-73 |
| Events on GlobalBus: `installation.update_available`, `installation.updated` | `packages/schema/src/installation-event.ts`, emitted `cli/upgrade.ts` ~16-50 |
| **No check cache** — one registry GET per TUI boot | `cli/upgrade.ts` (no cache path exists) |

## claude-swap (v0.27.0b1, Python — same ecosystem as cam)

| Fact | Source |
| --- | --- |
| `PYPI_URL = https://pypi.org/pypi/claude-swap/json`, `info["version"]`, `urlopen(timeout=2)` | `src/claude_swap/update_check.py` ~16, ~57-61 |
| Cache: `CACHE_DIR/update_check.json`, TTL 24h; **`write_cache` runs on the failure path too** — a dead network suppresses re-checks for a day | `update_check.py` ~14-15, ~52-66; `cache.py` `read_cache`/`write_cache`/`MISSING` |
| `_detect_install_method()`: `sys.prefix` adjacent-part pairs — `("uv","tools")` → `uv`, `("pipx","venvs")` → `pipx`; `UV_TOOL_DIR`/`PIPX_HOME` trusted **only** when `prefix.is_relative_to(root)` | `update_check.py` ~23-43 |
| `_parse_version`: `tuple(int(x) for x in v.split("."))` — crashes on `1.2.0rc1`; the outer `except Exception` turns that into silence (a fragility we fix, not copy) | `update_check.py` ~19-20, ~88-89 |
| `run_self_upgrade()`: `["uv","tool","upgrade","claude-swap"]` or `["pipx","upgrade","claude-swap"]`; unknown method → prints all three manual commands (uv / pipx / `python -m pip install --upgrade`), exit 1; `FileNotFoundError` → "PM not on PATH" exit 1 | `update_check.py` ~92-135 |
| Windows: prints the command instead of running — the running `cswap.exe` holds a file lock; user re-runs after exit releases it | `update_check.py` ~119-125 |
| Notice printed to **stderr** after the command's payload; skipped on `--purge` (would recreate the just-deleted cache dir), `--upgrade`, `--json` | `cli.py` ~1482-1490 |
| `--upgrade` dispatch runs **before** switcher init — self-upgrade never touches config/keychain | `cli.py` ~1355-1365 |

## ai-usagebar (v1.14.0, Rust — the download+swap model; discipline applies, mechanism does not)

| Fact | Source |
| --- | --- |
| Pure decisions split from glue: `src/update.rs` owns `is_newer`, `parse_release`, `select_downloads`, sha256-sidecar parse, `stage_swap` — unit-tested on every OS | `src/update.rs`, called from `tray/update_flow.rs` ~16-19 |
| `check_at`: non-2xx → error naming the **HTTP status, never the body** ("upstream body may name the account; it must not reach the UI"); prerelease/draft → `Ok(None)`, not an error | `tray/update_flow.rs` ~52-84, ~243-264 |
| Downloads: HTTPS-only refusal, `content_length` cap **and** post-read byte cap, sha256 sidecar verified before staging, dev-build (`debug_assertions`) refusal | `tray/update_flow.rs` ~89-156 |
| UA: `ai-usagebar-tray/<CARGO_PKG_VERSION>` | `tray/update_flow.rs` ~26 |

## Facts verified live 2026-10-09 (not from a repo)

| Fact | How |
| --- | --- |
| `https://pypi.org/pypi/claude-acc-manager/json` → `info.version = "1.1.0"` | `curl` |
| `uv-receipt.toml` lives at `<uv-tool-dir>/<pkg>/uv-receipt.toml`; registry install records `requirements = [{ name, specifier = "==1.1.0" }]` — **distinguishes PyPI from `git`/`path`/`url` requirements** (git-sourced `uv tool upgrade` re-resolves the ref, not the release) | `cat ~/.local/share/uv/tools/claude-acc-manager/uv-receipt.toml`; this machine's cam is uv-PyPI-installed |
| pipx equivalent: `pipx_metadata.json` `main_package.package_or_url` holds a canonical PEP 508 string — `name[extras]<spec>` for an index install; `name @ url`, a bare URL, or a resolved absolute path otherwise | pipx `src/pipx/package_specifier.py` (`_parsed_package_to_package_or_url`, `valid_pypi_name`), `src/pipx/pipx_metadata_file.py` — read from upstream `main` at T2 |
| `claude_acc_manager.package_version()` → `0.0.0+local` on unpacked checkouts | `src/claude_acc_manager/__init__.py` ~6-22 |

## The disagreements the milestone must decide

1. **Auto-apply or notify-only** — opencode installs patches silently; claude-swap never installs. → `updates.mode` three-way, default `notify` (maintainer, 2026-10-09).
2. **Trigger** — opencode fires at TUI boot; claude-swap at every command end. → both + `auto` event line; 24h cache makes extra triggers free.
3. **Version compare** — opencode uses `semver`; claude-swap's `int.split` crashes on prereleases. → stdlib-locked (ADR-0002): strict `^\d+(\.\d+)+$` release-tuple compare, non-release → not-an-update.
4. **Endpoint** — opencode asks the method's own registry; cam has one release source (PyPI) so per-method endpoints buy nothing. → PyPI JSON always.
