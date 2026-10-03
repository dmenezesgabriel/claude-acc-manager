# SL-010 — credential-write boundary: version-aware isolation, lock interop, op serialization

Milestone: defect-fix (user-reported failure on claude 2.1.287) · State: in-progress · Depends on: — · Closes: —

> Defect slice, not a roadmap milestone. Durable residue: ADR-0014 + comments. Evidence was gathered from the installed claude 2.1.287 binary (bunfs chunks read in place), npm tarballs `@anthropic-ai/claude-code` 0.2.126 / 1.0.128 / 2.0.77 extracted to /tmp/claude-versions, and strace probes under `CLAUDE_CONFIG_DIR` — all re-verifiable from this file.

## Outcome

`cam add` cannot silently capture or lose a credential: the launcher refuses claude versions that cannot isolate credentials (<1.0), strips env that redirects claude's credential store, cam mutations of any `.credentials.json` hold claude's own `.storage-write` lock, and add/remove/switch cannot move files out from under each other.

## Evidence gathered this session

### The observed failure (12:10, real machine) — root cause

Timeline from `~/.zsh_history` epochs + file mtimes: user's `cam add gdm` registered 12:08:55; my `cam add gdm` launched ~12:09:3x with claude mid-login; user opened `cam tui` 12:10:06 and switched to gdm 12:10:09 (`unclaimed/2026-10-03T15-10-09Z.json` + `~/.claude/.credentials.json` mtime 12:10:09.326 + `~/.claude.json` splice 12:10:09.385 — all one switch transaction). The switch **moved** `accounts/gdm/.credentials.json` into the live slot while the second add's claude was still logged in; add's read-back found no file → `error: no credentials in account dir … — login did not finish`. **Not a claude isolation defect**: strace shows 2.1.287 reads `.credentials.json` only from `CLAUDE_CONFIG_DIR` — cam raced itself.

### claude version matrix (binary + npm + strace, Linux)

| Version | `.credentials.json` store dir | `.claude.json` | credential mutation lock | secure-storage layer | `--version` output |
| --- | --- | --- | --- | --- | --- |
| 0.2.x | `~/.claude` **hardcoded** — `CLAUDE_CONFIG_DIR` ignored (`NR1` in cli.js) | `<CCD>/config.json` | not observed | none | `X.Y.Z (Claude Code)` |
| 1.0.x | `CLAUDE_CONFIG_DIR \|\| ~/.claude` (`a2()`) | `<CCD>/.claude.json` | `.claude.json.lock` (proper-lockfile) | none | same |
| 2.0.x | `CLAUDE_CONFIG_DIR \|\| ~/.claude` (`yQ()`) | same | same | none | same |
| 2.1.x | `CLAUDE_SECURESTORAGE_CONFIG_DIR`(defined→verbatim, empty→`~/.claude`) `\|\| CLAUDE_CONFIG_DIR \|\| ~/.claude` (`wS()`/`we()`) | same | + `<storageDir>/.storage-write` proper-lockfile, stale 15s (`dXr`) | secureStorage legs; keychain impls exist for macOS (`security` CLI) + Windows (CredMan, GrowthBook `tengu_windows_credman`) — **none for Linux** (no libsecret/dbus/secret_password in JS; leg selector `m(e)=F()&&e?re(e):ee`) | same |

### Key facts for the fixes

- `wS()` semantics (2.1.287): `CSSCD !== undefined` → `CSSCD || ~/.claude` (defined-but-empty ⇒ default store); else `CLAUDE_CONFIG_DIR || ~/.claude`. **An ambient `CSSCD` — set OR empty — redirects where claude reads/writes `.credentials.json`.** claude-swap mirrors exactly this (`credentials.py` ~line 74-107, cites 2.1.220 `getMacOsKeychainStorageServiceName`) and *refuses* to operate under a set `CSSCD` ("store-unmirrored").
- Refresh locks (2.1.287, `nKo`): `<wS()>/.oauth_refresh.lock` (stale 60s) **and** `<realpath(wS())>.lock` — cam's existing two locks still interop; both resolved under `wS()`, not `CLAUDE_CONFIG_DIR`.
- `.storage-write` (`dXr`): every secureStorage **mutation** holds `<wS()>/.storage-write` proper-lockfile `stale:15000`. cam holds nothing there today → cam writes race a live claude's credential mutations.
- Keychain item name `nze()`: `Claude Code-credentials[-sha256(dir)[:8]]` — hashed suffix present exactly when storage dir comes from `CCD` (unset `CSSCD`). Setting `CSSCD=<acct>` would **remove** the suffix and collide with the default item — so `CSSCD` must be *stripped*, never set.
- `claude auth status` (2.1.287) prints JSON `{loggedIn, email, configDirectory}` — viable future probe; not needed for this slice.
- `FileAccountStore._mutate` already serializes registry RMW under `<store>/.lock` (flock) — registry is not the hole; account dirs are.

## Who else implements this

| Repo | Has it | Entry points | Approach in one line |
| --- | --- | --- | --- |
| claude-swap | PARTIAL | `src/claude_swap/credentials.py`, `switcher.py`, `session.py` | mirrors `wS()` for reads (CSSCD→secure store, empty→default); refuses to operate when `CSSCD` set; no login-launcher so no env hygiene |
| ai-usagebar | ABSENT | — | `CLAUDE_CONFIG_DIR` model only; no secure-storage awareness |
| claude-code itself | — | `wS()`/`nze()`/`dXr`/`nKo` (2.1.287 binary) | the contract being mirrored: `CSSCD||CCD||~/.claude`, `.storage-write`, legacy+primary refresh locks |

**Count:** 1.5 of the references implement parts of this. The boundary mirror is justified by interoperability, not invention.

## Gap analysis — ours vs the contract

| Concern | Ours today | Contract (evidence) | Gap |
| --- | --- | --- | --- |
| live creds path | `path_resolver.credentials_path` = `CCD\|\|~/.claude` | `wS()` = `CSSCD‖CCD‖~/.claude` | diverges when `CSSCD` exported — cam reads/writes the wrong slot |
| credential locks | `.oauth_refresh.lock` + `~/.claude.lock` under `claude_config_home` | same two locks but under `wS()`; plus `.storage-write` per mutation | missing `.storage-write`; wrong base dir under `CSSCD` |
| launcher env | strips credential-supply vars; `CCD=<acct>` | `CSSCD` (set or empty) redirects the credential store; keychain-name hash depends on it | `CSSCD` leaks into the child |
| add vs switch/remove | no serialization | mutual exclusion needed across the whole add | missing → the observed defect |
| claude version | unchecked | 0.2.x cannot isolate credentials | add proceeds → silent wrong-slot capture |

## Trade-offs and what we adopt

| Axis | Options seen | Trade-off | Our choice, and why |
| --- | --- | --- | --- |
| `CSSCD` in cam's own resolution | claude-swap → mirror `wS()` for reads · claude-swap autoswitch → refuse under `CSSCD` | mirror = correct under every env; refuse = simpler | **Mirror** — the "live slot" is by definition what claude resolves; refusing punishes a legitimate env |
| `CSSCD` in the add child | set it (`<acct>`) · strip it | set removes the keychain-name hash (item collision) and is redundant for the file backend | **Strip** — `CCD` alone isolates both backends |
| `.storage-write` granularity | transaction-level (inside `credentials_locked`) · per-write (adapter) | transaction-level deadlocks: `mkdir_lock` is not reentrant and claude itself locks per-mutation | **Per-write inside the file adapters** — same discipline as upstream `dXr` |
| op serialization | per-account locks · store-wide lock · pending-marker file | per-account needs multi-lock ordering for switch's two dirs; marker re-invents lock semantics (staleness) | **Store-wide flock `<store>/.ops.lock`** held by add/remove/switch — minimum code, covers the observed race and every cam-vs-cam account-dir mutation; readers never take it |
| version floor | mirror all layouts · refuse <1.0 | 0.2.x also differs on `.claude.json`/`config.json` schema — supporting it re-opens ADR-0004's rejected copy-model | **Refuse <1.0** at `cam add` (only the login path needs it — the live slot layout is identical across versions when `CCD` unset) |
| rotation write (`persist_rotation`) | ops lock · `.storage-write` only | ops lock during fetch would stall all usage polling behind a long add | **`.storage-write` only** — write is atomic; worst case is a resurrected parked file, which the existing `_is_live` guard + quarantine contain |

## Surface

| Layer | Files |
| ----- | ----- |
| domain | — (no domain change) |
| application (ports / use cases) | `accounts/application/ports.py` (+`OpsLockPort`), `use_cases/add_account.py`, `use_cases/remove_account.py`, `use_cases/switch_account.py` |
| infrastructure | `accounts/infrastructure/path_resolver.py`, `accounts/infrastructure/claude_locks.py`, `accounts/infrastructure/active_slot.py`, `accounts/infrastructure/account_dir_files.py`, `accounts/infrastructure/account_credential_store.py`, `accounts/infrastructure/claude_login_launcher.py`, `accounts/infrastructure/ops_lock.py` (new) |
| cli / tui | `cli/dispatch.py` (TimeoutError → error), `__main__.py` (wiring) |
| tests | `test/support/fake_ops_lock.py` (new), launcher/add/switch/remove/locks/resolver/dispatch tests |
| docs | `docs/adr/0014-*.md` (new), `docs/architecture.md` §3, `docs/adr/0004` consequence note |

## Tasks

- [x] T1 — `fix(accounts): mirror claude's secure-storage dir for the live slot` — `secure_storage_home(env, home)` in path_resolver (`CSSCD` defined→verbatim-or-`~/.claude`, else `CCD||~/.claude`); `credentials_path`, `oauth_refresh_lock_dir`, `credentials_lock_dir` derive from it; `credentials_lock_dir` keeps sibling-`.lock` semantics on the resolved dir.
- [x] T2 — `fix(accounts): hold claude's .storage-write for every .credentials.json mutation` — `storage_write_lock(config_dir)` in claude_locks (mkdir, stale 15s, upstream `dXr`); wire `ActiveSlotAdapter.write/delete_credentials`, `AccountDirFiles.write/delete_credentials`, `AccountCredentialStore.persist_rotation`.
- [x] T3 — `fix(accounts): strip CLAUDE_SECURESTORAGE_CONFIG_DIR from the login env` — join `_CREDENTIAL_ENV_VARS`, comment cites `wS()`/`nze()`.
- [x] T4 — `feat(accounts): refuse cam add on claude <1.0` — `--version` probe in launcher, semver parse, `ValueError` naming the version + floor; missing binary stays `False`.
- [x] T5 — `fix(accounts): serialize account-mutating ops under a store ops lock` — `OpsLockPort` + `FlockOpsLock` (`<store>/.ops.lock`, `exclusive_file_lock`); `AddAccount`/`RemoveAccount`/`SwitchAccount._transact` hold it (ops outermost, then claude locks); composition root wiring; fake in `test/support/`.
- [x] T6 — `fix(cli): surface lock timeouts as errors not tracebacks` — dispatch catches `TimeoutError`.
- [x] T7 — docs: ADR-0014, architecture §3 lock row, ADR-0004 consequence note (2.1.287 re-probe result), PRD checkboxes.

## Manual validation (exit gate)

Hermetic end-to-end: `HOME=/tmp/h XDG_DATA_HOME=/tmp/d` + PATH-stub claude → real `cam add` while a second `cam` mutates (switch/remove) — must serialize, not corrupt; `cam add` against stub `--version` `0.2.126` → clean refusal; stub with `CSSCD` exported → env absent in child; `.storage-write` dir created+removed around writes. Plus real `cam add`-path smoke against installed `claude` 2.1.287 (version probe passes; no OAuth needed — the refusal/probe runs pre-login).

## Out of scope

- macOS/Windows keychain interop (repo is Linux-only, architecture §"Linux only"); the file backend is the only Linux leg (evidence above).
- 0.2.x support — refused, not ported (would require the rejected copy-model).
- `persist_rotation` vs concurrent switch residual window (documented choice above).
- Docker-based version matrix — evidence came from strace + binary/npm analysis instead; real-login behavior per version cannot be automated (OAuth).
