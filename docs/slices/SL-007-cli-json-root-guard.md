# SL-007 — full CLI surface: `--json` contract, root guard, `enable`/`disable`

Milestone: M7 · State: in-progress · Depends on: SL-006 (shipped) · Closes: GAP-006, GAP-002

## Outcome

A user can drive `cam` from scripts — `cam list|status|usage|switch --json` emits a stable schema-v1 JSON object on stdout — can park and return accounts with `cam disable <name>` / `cam enable <name>`, and is refused with a clear error when invoking `cam` as root outside a container.

## Exit gate

`uv run pre-commit run --all-files` clean · full `uv run pytest` green · then the manual validation below, run by a human or scripted against the real tool. Measurements go in the closing commit's body.

1. On an isolated `HOME` + `XDG_DATA_HOME`, register two accounts, `cam list --json | python -m json.tool`, `cam status --json`, `cam usage <name> --json`, `cam switch --dry-run --json` — each prints one parseable object carrying `"schemaVersion": 1`.
2. `cam disable <name>` on the active account prints the stays-live note; disabling the last enabled account prints the empty-rotation warning; `cam enable <name>` restores it. `cam list` shows `[disabled]`/`[quarantined]` markers.
3. `cam usage <unknown>` under `--json` prints the error envelope on stdout and exits 1.
4. Root refusal: `sudo cam list` → `error: refusing to run as root (outside a container)`, exit 1; a container-marker run (`sudo env container=cli cam list`, or inside a container) passes.

## Who else implements this

| Repo | Has it | Entry points | Approach in one line |
| --- | --- | --- | --- |
| claude-swap | FULL | `research_repos/claude-swap/src/claude_swap/cli.py`, `research_repos/claude-swap/src/claude_swap/json_output.py`, `research_repos/claude-swap/src/claude_swap/switcher.py` | Global `--json` restricted post-parse to list/status/switch; handlers return payload dicts and the CLI does the single `json.dumps`; error envelope to stdout; `set_account_disabled`; `_guard_root` with env/dockerenv/cgroup/mountinfo container probes. |
| ai-usagebar | PARTIAL | `research_repos/ai-usagebar/src/widget/cli.rs` (`AccountAction::Status { json }`), `research_repos/ai-usagebar/src/account.rs` (`status`) | Per-subcommand `--json` flag on `account status` only; serde_json report printed compact. No enable/disable (config has no enabled flag), no root guard. |
| claude-code itself | — | — | No interop surface this milestone — we touch no claude-owned file format. The root guard protects *its* files (`~/.claude`, `~/.claude.json`) from root-owned writes. |

Note: `docs/research/parity-matrix.md`'s root-refusal row marks claude-swap `—`, but `_guard_root` exists and fires in the main dispatch plus every pre-dispatched command — the capability is FULL and this milestone ports it. The matrix row is corrected at ship.

**Count:** 1 of 2 implementable references has all three features (ai-usagebar is PARTIAL on `--json` only). Enable/disable and the root guard are claude-swap ports; the `--json` schema adopts claude-swap's contract conventions scaled to our command set.

## Implementation inventory

### claude-swap

| Concern | Files |
| --- | --- |
| `--json` flag + restriction | `research_repos/claude-swap/src/claude_swap/cli.py` — global `--json` argument (~L1105), `parser.error` restriction to list/status/switch (~L1313), command-flag compatibility checks (~L1310–1356) |
| Single serialization point | `research_repos/claude-swap/src/claude_swap/cli.py` — `payload` return contract + `json.dumps(payload, indent=2)` (~L1375, L1478); error envelope on stdout in JSON mode (~L1461); KeyboardInterrupt → 130, note on stderr under `--json` (~L1469) |
| Payload builders | `research_repos/claude-swap/src/claude_swap/json_output.py` — whole file: `SCHEMA_VERSION`, `_window_to_json`, `usage_to_json`, `usage_fields`, `account_ref`, `usage_freshness_fields`, `usage_failure_fields`, `last_good_usage_fields`, `account_row`, `error_envelope`, `_timestamp` |
| Payload assembly | `research_repos/claude-swap/src/claude_swap/switcher.py` — `_build_list_payload` (~L5463, decision-grade `entry.decision_value()`), `_build_status_payload` (~L5631), `_switch_result_from_op`/`_switch_noop` (~L5748, `switched`/`from`/`to`/`strategy`/`reason`/`message`/`warnings`), `switch`/`switch_to` `json_output` params (~L5807, L6198) |
| enable/disable | `research_repos/claude-swap/src/claude_swap/switcher.py` `set_account_disabled` (~L1861): already-in-state no-op notice, active-account stays-live note, empty-rotation warning, back-in-rotation note; dispatch at `cli.py` ~L1395 |
| Root guard | `research_repos/claude-swap/src/claude_swap/cli.py` `_guard_root` (~L232) + main-dispatch copy (~L1379): `geteuid()==0 and not _is_running_in_container()` → stderr + exit 1 |
| Container detection | `research_repos/claude-swap/src/claude_swap/switcher.py` `_is_running_in_container` (~L389–426): `CONTAINER`/`container` env → `/.dockerenv` → `/proc/1/cgroup` (docker/lxc/containerd/kubepods) → `/proc/self/mountinfo` (docker/overlay); `PermissionError` on a read is skipped |
| Usage projection inputs | `research_repos/claude-swap/src/claude_swap/usage_store.py` — `UsageEntry` (last_good, fetched_at, last_error, backoff_until, `decision_value()`, `in_backoff()`) |
| Pace fields | `research_repos/claude-swap/src/claude_swap/pace.py` — `compute_pace`, `projected_exhaustion_ts`, `will_last_to_reset`; **not ported** (no consumer — see Deviations) |

### ai-usagebar

| Concern | Files |
| --- | --- |
| `--json` flag shape | `research_repos/ai-usagebar/src/widget/cli.rs` — `AccountAction::Status { json }` (~L246): a per-subcommand clap flag, not a global one |
| Status payload | `research_repos/ai-usagebar/src/account.rs` `status` (~L98–231): builds one serde_json report (`cli`/`desktop`/`usage_accounts`), `println!("{report}")` for `--json`, same value feeds the human renderer |

## Trade-offs and what we adopt

| Axis | Options seen (repo → approach) | Trade-off | Our choice, and why |
| ---- | ---------------------------- | --------- | ------------------- |
| `--json` flag placement | claude-swap → one global flag + post-parse `parser.error` whitelist; ai-usagebar → per-subcommand flag | A global flag cannot follow a positional subcommand in argparse (`cam list --json` would error); per-subcommand needs no whitelist code | Per-subcommand `--json` on `list`/`status`/`usage`/`switch` — ai-usagebar's shape; other subcommands reject it via argparse's exit-2 for free |
| Serialization point | both → commands build payloads, one `json.dumps` at the boundary | Drift if handlers print JSON themselves | Same: handlers return `int | dict[str, object]`; `run()` serializes once, `indent=2` |
| Error channel in JSON mode | claude-swap → `error_envelope` on **stdout**, exit 1 | stderr text would break `| jq` pipelines | Adopt: `{"schemaVersion":1,"error":{"type","message"}}` on stdout |
| Schema casing/version | claude-swap → camelCase + `schemaVersion: 1`; ai-usagebar → snake_case serde names, no version | Consistency with the richer contract | camelCase + `schemaVersion` on every payload |
| usageStatus sentinels | claude-swap → ok/token_expired/api_key/keychain_unavailable/relogin_required/foreign_credential/no_credentials/unavailable | Most sentinels name states our model lacks | Port the subset: `ok`, `unavailable`, `relogin_required` (quarantined names); a missing credential reads `unavailable` + `usageError:"no-credential"` |
| Account reference shape | claude-swap → `{number, email}`; ours is name-keyed | No slot numbers exist here | `{name, email}` objects; registry `active` field carries a name, not a number |
| Decision-grade usage in rows | claude-swap → `entry.decision_value()` (trusted only within staleness bound), else `unavailable` + `lastGood*`/`usageError`/`usageRetryAt` | Old measurements must not drive scripts | Port: `trust_ok(entry, now, earliest_future_reset_epoch, TRUST_MAX_AGE_S)` gates `ok`; untrusted rows keep `lastGood*` + failure fields |
| Root-guard probes | claude-swap → env vars, `/.dockerenv`, `/proc/1/cgroup`, `/proc/self/mountinfo` | The `overlay` mountinfo substring is blunt (bare-metal overlayfs exists) | Port verbatim — reference parity beats a locally-invented heuristic; imprecision noted in Deviations |
| Root refusal channel | claude-swap → always plain stderr, even under `--json` | A stderr line is invisible-but-benign to `| jq`, yet ours is a cheap fix | Under `--json` emit the envelope on stdout; otherwise the stderr line; exit 1 both ways |
| enable/disable notices | claude-swap → four notices around the confirmation | The extras prevent real footguns (silent no-op; disabling the live login; emptying rotation) | Port all four (user decision) |
| Human `list` markers | claude-swap → ` (active)`/` (disabled)` suffixes | Without a marker a disabled/quarantined account is invisible until rotation mysteriously skips it | Append `[disabled]`/`[quarantined]` suffixes to `list` rows |

## Gap analysis — what we already have vs the references

| Concern | Ours today (file) | Best reference (file) | Gap |
| ------- | ----------------- | --------------------- | --- |
| `--json` flag | absent — `src/claude_acc_manager/cli.py` `build_parser` | claude-swap `cli.py` ~L1105 | absent |
| Payload builders / schema | absent | claude-swap `json_output.py` | absent |
| Error envelope | absent — `run()` prints `error:` to stderr | claude-swap `cli.py` ~L1464 | absent |
| Root guard | absent — `docs/architecture.md` §8.6 plans it | claude-swap `cli.py` ~L232, L1380 | absent |
| Container probe | absent | claude-swap `switcher.py` ~L389 | absent |
| enable/disable use case | `src/claude_acc_manager/accounts/application/use_cases/set_account_enabled.py` — complete, store + selection exclusion shipped M6 | claude-swap `switcher.py` ~L1861 | present, unreachable from CLI |
| enable/disable command | absent | claude-swap `cli.py` ~L1395 | absent |
| Disabled marker in `list` | absent — `enabled` persisted, never rendered | claude-swap `switcher.py` ~L5557 | absent |
| Quarantined marker in `list` | absent — `store.quarantined()` exists (M6) | — (claude-swap surfaces it via usageStatus) | absent |
| KeyboardInterrupt handling | absent — propagates as traceback | claude-swap `cli.py` ~L1469 | absent |
| Cached-usage projection | absent — `UsageCacheEntry` fields exist (`usage_cache_entry.py`), `trust_ok` exists (`cache_trust.py`) | claude-swap `usage_fields`/`account_row` | logic absent, inputs present |

## Schema-v1 contract

Every payload is one `json.dumps(payload, indent=2)` object on stdout, keys camelCase, `schemaVersion` always 1.

- `cam list --json` → `{schemaVersion, active: <name>|null, accounts: [{name, email, accountUuid, organizationUuid, organizationName, isOrganization, active, enabled, quarantined, usageStatus, usage, ...}]}`.
  - `usage` = `{fiveHour: {pct, resetsAt?}, sevenDay: {...}, scoped: [{name, pct, resetsAt?}]}` when decision-grade, else `null`.
  - Trusted row adds `usageFetchedAt` (ISO-Z) + `usageAgeSeconds`; untrusted row adds `lastGoodUsage`, `lastGoodFetchedAt`, `lastGoodAgeSeconds` and, when a failure is recorded, `usageError` + `usageRetryAt` (only while `in_backoff`).
  - `usageStatus`: `ok` | `unavailable` | `relogin_required` (quarantined names).
- `cam status --json` → `{schemaVersion, active: {email, accountUuid, organizationUuid, organizationName, isOrganization, managed: true, managedAs, <same usage fields>} | null, totalManagedAccounts}`; an unmanaged live login yields `active: {email, accountUuid, organizationUuid, organizationName, managed: false}` (no usage keys); no login yields `active: null`.
- `cam usage <name> --json` → `{schemaVersion, account, usageStatus: "ok"|"unavailable", usage|null, stale, usageError|null, permanentAuthError, quarantined}` (`quarantined: true` only when this run tombstoned the lineage — the side-effect print folds into the payload).
- `cam switch --json` → `{schemaVersion, dryRun, switched, outcome, from: {name,email}|null, to: {name,email}|null, unmanagedLive, preservedTo|null, strategy|null, skipped: [{name,reason}], quarantined: [names], message}` — `message` is the human line (claude-swap ships one too); `from:null` + `unmanagedLive:true` when the outgoing login is foreign.
- Errors under `--json` → `{"schemaVersion":1,"error":{"type":<exc class name>,"message":<str(exc)>}}` on stdout, exit 1. Argparse failures (bad flags, unknown `--json` target) stay exit 2 on stderr — unchanged.
- `KeyboardInterrupt` → exit 130; the cancelled note goes to stderr under `--json`, stdout otherwise.

## Deviations

- `--json` is per-subcommand, not global — argparse subparsers can't hold a global flag after the verb (ai-usagebar's shape; identical `cam list --json` UX).
- `cam usage <name> --json` exists — no claude-swap counterpart (its usage rides inside list/status); ours is a standalone command, so the same projection is exposed there (user decision).
- Root refusal emits the error envelope under `--json` — claude-swap prints plain stderr there; ours keeps stdout machine-readable per the contract.
- Account refs are `{name, email}` — our registry is name-keyed, no slot numbers exist.
- `enabled: bool` and `quarantined: bool` are always present on list rows — v1 has no consumers to protect; claude-swap's additive `disabled` exists for schema continuity we don't need.
- Pace fields (`expectedPct`, `projectedExhaustionAt`, `willLastToReset`) are not ported — no pace model exists here and no consumer wants it (claude-swap issue #125 feature). Revisit only if M9's auto loop needs it.
- `spend`/`extra_usage` and `loginExpiresAt` are not ported — spend is deferred by ADR-0012; we store no login-expiry metadata.
- The mountinfo `overlay` substring is a blunt container signal (bare-metal overlayfs false-positives possible) — ported verbatim for reference parity.
- Human `list` gains `[disabled]`/`[quarantined]` markers — additive output so the new state is visible without `--json`.

## Open decisions

None — the three scope questions (cached usage in `list --json`; `usage --json` existence; enable/disable notice fidelity) were settled with the user at pickup: include, add, port.

## Surface

| Layer | Files |
| ----- | ----- |
| domain | — (no domain changes) |
| application (ports / use cases) | `src/claude_acc_manager/accounts/application/use_cases/set_account_enabled.py` (exists — wired); `src/claude_acc_manager/usage/application/ports.py` `ClockPort` (existing, injected into the CLI bundle) |
| shared | `src/claude_acc_manager/shared/container.py` (new — `running_in_container(env, fs_root)`) |
| cli / tui | `src/claude_acc_manager/cli.py` — subparsers, `_cmd_*` handlers, `ProcessContext`, root guard, `UseCases` (+`set_enabled`, +`usage_clock`); splits into a `cli/` package (`parser`/`commands`/`dispatch`/`json_output`/`__init__` re-exports) only if it crosses the 500-line ceiling (ADR-0013 trigger) |
| composition root | `src/claude_acc_manager/__main__.py` — wire `SetAccountEnabled`, `UsageSystemClock`, `ProcessContext(os.geteuid(), running_in_container(...))` |
| tests | `test/unit/test_cli.py` (+ `test/unit/cli/` mirror if the package splits), `test/unit/shared/test_container.py`, `test/unit/test_main.py` call sites |
| config | `pyproject.toml` — import-linter `cli` contract covers submodules + forbids `usage.infrastructure`, only if the split lands |

## Tasks

One TDD unit each, one conventional commit each. `run()`'s `process=` kwarg and the test call-site updates land in the same commit as the guard — no dead intermediate.

- [ ] T1 — `shared/container.py::running_in_container(env, fs_root)` + hermetic tests (env vars, dockerenv, cgroup/mountinfo contents, unreadable file skipped). `feat(shared): detect container runtimes for the root guard`
- [ ] T2 — `ProcessContext` + root refusal inside `run()` after parse (so `--help` works as root); `__main__` supplies real probes; test sites route through a helper passing non-root. `feat(cli): refuse to run as root outside containers`
- [ ] T3 — `cam enable`/`disable` subparsers + `UseCases.set_enabled` + `__main__` wiring + the four notices. `feat(accounts): wire cam enable and disable`
- [ ] T4 — `list` `[disabled]`/`[quarantined]` markers. `feat(accounts): mark disabled and quarantined accounts in list`
- [ ] T5 — `usage --json` + the JSON plumbing: `SCHEMA_VERSION`, `_timestamp`, window projection, `error_envelope`, handler `int | dict` return contract, single `json.dumps`, envelope on `KeyError`/`ValueError`, `KeyboardInterrupt` → 130. `feat(cli): emit usage --json and the error envelope`
- [ ] T6 — `list --json` account rows + cached decision-grade usage (`UseCases` gains `usage_clock`; `__main__` wires `UsageSystemClock`). `feat(cli): emit list --json with cached usage`
- [ ] T7 — `status --json`. `feat(cli): emit status --json`
- [ ] T8 — `switch --json` (from/to `{name,email}`, skipped, quarantined, preservedTo, dryRun, strategy, message). `feat(cli): emit switch --json`
- [ ] T9 — if `cli.py` crosses 500 lines: split into the `cli/` package (re-export `run`/`UseCases`/`ProcessContext` from `__init__`), extend the import-linter contract to `claude_acc_manager.cli.*` + forbid `usage.infrastructure`. `refactor(cli): split the transport into a package`
- [ ] T10 — ship: manual validation above; closing commit body carries gate numbers; backlog M7 row → `shipped`; parity-matrix GAP-002/GAP-006/root-refusal rows corrected; this file deleted.

## Out of scope

- `--json` on `add`/`remove`/`enable`/`disable` — neither reference serializes mutations; the flag is absent there (argparse exit 2).
- `cam auto --json` JSONL events — M9 owns the auto surface.
- `cam tui` — M8.
- `settings.json` / `cam config` — M9 (GAP-007).
- `unclaimed` listing, duplicate/lockstep warnings, aliases, `--slot`, export/import — capabilities we deliberately lack (architecture §11).
- Windows `geteuid` shim — Linux-only per architecture §2.
