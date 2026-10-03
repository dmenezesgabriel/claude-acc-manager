# SL-011 — claude-version contract gate: floor 2.1.144, fail-closed on unverified bands

Milestone: M10 · State: in-progress · Depends on: — · Closes: —

> Evidence lives in `docs/research/claude-contract-matrix.md` (R-session, verified 2026-10-03). Band boundaries below are grep-pinned against `/tmp/claude-versions/` bundles + native binaries and `~/.local/share/claude/versions/` — all `test -e`'d.

## Outcome

`cam` probes `claude --version` and refuses to run any operation that writes `.credentials.json`, splices `.claude.json`, or launches claude unless the installed version is inside the verified contract band `>=2.1.144, <2.2.0` — with `CAM_ASSUME_CLAUDE_CONTRACT` as the deliberate override. Read-only commands never gate.

## Exit gate

`uv run pre-commit run --all-files` clean · full `uv run pytest` green · then the manual validation below. Measurements go in the closing commit's body.

1. PATH-stub `claude` reporting `0.2.126`, `1.0.128`, `2.0.77`, `2.1.100`, `2.1.143` → `cam switch`/`cam usage`/`cam auto --once` refuse with the version named; `cam add` refuses at launch.
2. Stub `2.1.144`, `2.1.288` → same commands proceed past the gate.
3. Stub `2.2.0`, `3.0.0` → refuse, naming the override; `CAM_ASSUME_CLAUDE_CONTRACT=1` → proceed.
4. `cam list`/`status`/`config`/`remove` work with no `claude` on PATH at all.
5. `cam usage <acct>` with an unexpired token proceeds with claude absent; with an expired token it refuses *before* any refresh POST (stub transport asserts zero requests).
6. Real `claude` 2.1.287 → `cam status`/`cam usage`/`cam auto --once` unaffected.

## Who else implements this

| Repo | Has it | Entry points | Approach in one line |
| --- | --- | --- | --- |
| claude-swap | PARTIAL | `src/claude_swap/credentials.py`, `session.py`, `process_detection.py` | refuses operations under a set CSSCD (one unverifiable env → refuse); `claude auth status` as login probe; session-PID detection for live processes — no version gate anywhere |
| ai-usagebar | ABSENT | — | `CLAUDE_CONFIG_DIR` model only; no version probing at all |
| claude-code itself | — | contract artifacts in matrix | the contract being verified per version band |

**Count:** 0.5 of the references implement a version-adjacent refusal (env-shape, not semver). cam's semver gate is an invention justified by the matrix: the contract *does* vary by version, measurably.

## Implementation inventory

### claude-swap

| Concern | Files |
| --- | --- |
| CSSCD-aware storage resolution + refusal | `src/claude_swap/credentials.py` (~74–117, wS-mirror + "store-unmirrored" refuse) |
| `claude auth status` local probe | `src/claude_swap/session.py` (~200, ~822, ~955) |
| Live-session detection (not adopted) | `src/claude_swap/process_detection.py` |

### claude-code (the contract, per `docs/research/claude-contract-matrix.md`)

| Concern | Evidence |
| --- | --- |
| Full contract present from 2.1.144 | `.storage-write` ≥2.1.136, `CLAUDE_SECURESTORAGE_CONFIG_DIR` ≥2.1.144, `.oauth_refresh.lock` ≤2.1.70 |
| Band-internal drift | `.oauth_refresh.lock` `stale:1e4`→`stale:60000,update:5000` between 2.1.150 and 2.1.218; `.design_oauth_refresh.lock` appears 2.1.218 |
| `--version` format `X.Y.Z (Claude Code)` | stable 0.2.x → 2.1.288 incl. native binaries |
| Launcher env hazard classes | 2.1.288 binary env sweep (matrix table) |

## Gap analysis — ours vs the evidence

| Concern | Ours today (file) | Evidence | Gap |
| --- | --- | --- | --- |
| Version floor | `claude_login_launcher.py` `MIN_SUPPORTED_VERSION=(1,0,0)`, `add`-path only | contract complete only ≥2.1.144 | wrong floor, enforced on one path |
| Upper bound | none | band drift is real (matrix) | ≥2.2 proceeds silently everywhere |
| Switch/switch-back interop | `MkdirClaudeLock` assumes 2.1.x lock set | those locks don't exist <2.1.136 | switch races a <2.1.136 live claude |
| Refresh/persist path | `fetch_account_usage.py`, `freshen_target.py` no gate | one-time-use refresh tokens (ADR-0009) + `.storage-write` interop | consumes tokens under an unverified contract |
| Probe reuse | `_probe_version` private to launcher | gate needed on 4 paths | extract shared mechanism |
| Error surface | dispatch maps `TimeoutError`/`ValueError` | refusals need a stable `--json` type | new `UnsupportedClaudeVersion` exception |
| Launcher env | 6-var strip list | ≥9 hazard classes in 2.1.288 (matrix) | ambient env can redirect/supply the scoped login |
| Contract knowledge | literals scattered across `path_resolver`/`claude_locks`/launcher | one version → one contract | no single band model, no re-verification procedure |

## Trade-offs and what we adopt

| Axis | Options seen (repo → approach) | Trade-off | Our choice, and why |
| ---- | ------------------------------ | --------- | ------------------- |
| Gate placement | per-command (cli) · per-use-case | cli-level misses TUI callers; use-case covers every transport | **Use-case level** — `SwitchAccount.execute`, `FetchAccountUsage._resolve_access_token` pre-refresh, `FreshenTarget._refresh` pre-refresh, launcher for `add`. TUI and `cam auto` inherit through the use cases (engine's except→ERROR covers the loop) |
| Usage gating granularity | gate `execute()` · gate before refresh | `execute()` blocks pure cache/live reads; refresh is the first irreversible act (one-time-use token → persist needs contract) | **Before `refresher.refresh()`** — reads stay ungated; never consume a token we can't persist |
| Reads under unverified claude | refuse · proceed | file schema is version-stable (matrix); reads race nothing | **Proceed** — `list`/`status`/`config`/`remove`/cache-hits never probe |
| Probe failure (absent/unparseable) | allow · refuse | fail-closed doctrine (user decision) | **Refuse mutating ops**; reads unaffected; override covers the absent case too |
| Override | CLI flag · env var · `cam config` key | flag needs plumbing per command; persisted key is a footgun that outlives the mismatch | **`CAM_ASSUME_CLAUDE_CONTRACT` env var** — non-empty bypasses the band check (contract marked `assumed`), explicit per-run, works for the systemd `cam auto` case |
| Port per component | one shared port · per-component ports | `usage` can't import `accounts`; `auto`'s freshen already imports `usage` ports | **Per-component `ClaudeContractProbePort`** in `accounts/` + `usage/` `application/ports.py` (SystemClock precedent); adapters per component subclassing their port, all delegating to `shared/claude_contract.py` |
| `auto` re-probe | engine probes per tick · use cases probe per call | engine-level is one probe but goes stale mid-tick | **Per-call probing** — every gated call site probes at mutation time; a mid-loop claude update is caught at the next mutation, not next tick |
| `auth status` as probe | adopt · not now | richer JSON but unverified shape on the floor version; `--version` suffices for the gate | **Not adopted** — `--version` is uniform across all bands (matrix) |
| Floor granularity | `>=2.1.0` · `>=2.1.144` · `>=2.1.218` | 2.1.0–.143 each lack a different contract subset; .144 has full contract; staleness drift inside band is safe-direction | **`>=2.1.144`** — first version carrying wS()+`.storage-write`+`.oauth_refresh.lock` together |

## Deviations

- No `cam doctor`/compat surface — the gate's error message is the surface; a diagnostic command is out of scope (minimum code).
- `cam auto` refusal surfaces as `ErrorEvent` + `TickOutcome.ERROR` (exit 1 under `--once`) — no new outcome variant; a looping refusal keeps erroring per tick, which is visible rather than silent.
- claude-swap's session-PID detection not ported — floor ≥2.1.144 gives real lock interop; detection solves the no-locks problem cam no longer has.

## Open decisions

None blocking — floor and unknown-version policy are settled (evidence + user call). Deferred to code review if it resurfaces: whether `SwitchAccount` should probe before or after taking `.ops.lock` (current: probe first — a doomed wait never serializes).

## Surface

| Layer | Files |
| ----- | ----- |
| domain | `shared/claude_contract.py` (new — `ClaudeContract` VO, band constants, `contract_for_version`, `probe_claude_version`, `probe_claude_contract`, `UnsupportedClaudeVersion`, `CAM_ASSUME_CLAUDE_CONTRACT`) |
| application (ports / use cases) | `accounts/application/ports.py` (+`ClaudeContractProbePort`), `usage/application/ports.py` (+`ClaudeContractProbePort`), `accounts/application/use_cases/switch_account.py`, `usage/application/use_cases/fetch_account_usage.py`, `auto/application/use_cases/freshen_target.py` |
| infrastructure | `accounts/infrastructure/subprocess_contract_probe.py` (new), `usage/infrastructure/subprocess_contract_probe.py` (new), `accounts/infrastructure/claude_login_launcher.py` (shared probe, new bounds, env strip expansion) |
| cli / tui | `cli/dispatch.py` (`UnsupportedClaudeVersion` → `error:`/`UnsupportedClaudeVersion` envelope), `__main__.py` (wiring) |
| tests | `test/support/fake_claude_contract.py` (new), contract unit tests, launcher tests, switch/fetch/freshen gate tests, dispatch test |
| docs | `docs/adr/0015-claude-version-contract-gate.md` (new), `docs/architecture.md` §3 contract row + §8 guarantee row |
| import-linter | `pyproject.toml` `ignore_imports` — two adapter→ports entries |

## Tasks

- [ ] T1 — `feat(shared): claude contract model — band check, probe, override, refusal error` — `shared/claude_contract.py` with `ClaudeContract` VO (`version`, `supported`, `assumed`, `reason`), `SUPPORTED_MIN=(2,1,144)`, `SUPPORTED_MAX_EXCLUSIVE=(2,2,0)`, `CAM_ASSUME_CLAUDE_CONTRACT`, `contract_for_version`, `probe_claude_version` (subprocess, reused regex+timeout), `probe_claude_contract(env, executable)` honoring the override, `UnsupportedClaudeVersion(ValueError)`, `ClaudeContract.require_supported()`. Unit tests: band edges (2.1.143/2.1.144/2.1.288/2.1.299/2.2.0/3.0.0), None version, override set/empty/unset, probe timeout+unparseable+nonzero-exit.
- [ ] T2 — `feat(accounts,usage): contract probe ports + subprocess adapters` — `ClaudeContractProbePort` in both `application/ports.py`; `SubprocessClaudeContractProbe` in both `infrastructure/` (env+executable injected); import-linter `ignore_imports` entries; `test/support/fake_claude_contract.py`.
- [ ] T3 — `fix(accounts): launcher floor 2.1.144 + upper bound + shared probe` — `ClaudeLoginLauncher` takes the probe port; `<2.1.144` refuses naming the contract introduction; `>=2.2.0` refuses naming the override; probe-failure refuses (ValueError today stays ValueError-compatible). Replace `MIN_SUPPORTED_VERSION` with shared constants.
- [ ] T4 — `feat(accounts): gate switch on the claude contract` — `SwitchAccount` takes the probe port, `require_supported()` at `execute()` top before `.ops.lock`. Tests: refusal prevents any slot/store mutation (failable fakes assert zero writes).
- [ ] T5 — `feat(usage,auto): gate refresh on the claude contract` — `FetchAccountUsage._resolve_access_token` + `FreshenTarget._refresh` call `require_supported()` immediately before `refresher.refresh()`. Tests: expired-token refusal asserts zero refresher calls AND zero persist_rotation calls; unexpired/cache paths never probe.
- [ ] T6 — `fix(accounts): strip credential-supply and redirect env from the login child` — expand `_STRIPPED_ENV_VARS` by the matrix's hazard classes (endpoint redirects, token/identity supply, federation store, `CLAUDE_ENV_FILE`), grouped and cited.
- [ ] T7 — `feat(cli): surface contract refusals as a distinct error` — dispatch catches `UnsupportedClaudeVersion` before `ValueError`, emits type `UnsupportedClaudeVersion`.
- [ ] T8 — `chore: wire contract probes in the composition root` — construct both adapters in `build_use_cases`, inject into launcher/switch/fetch/freshen.
- [ ] T9 — `docs(adr): ADR-0015 + architecture contract/guarantee rows` — band model, override, re-verification procedure (the matrix's grep commands as the durable recipe), launcher env doctrine; update `path_resolver`/`claude_locks` comments where they cite "2.1.x" loosely.

## Out of scope

- claude <2.1.144 support — refused, not ported (the contract subset differs by sub-range; re-deriving per-sub-range contracts is the unverified-band problem twice over).
- `auth status` JSON probe, `cam doctor`, session-PID detection — not needed for the gate.
- macOS/Windows keychain legs (Linux-only, architecture §1).
- `setup-token`/API-key/federation accounts (backlog non-goals).
