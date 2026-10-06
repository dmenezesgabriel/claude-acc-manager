---
status: accepted
date: 2026-10-03
---

# ADR-0015 — Mutating operations require a verified claude contract band; `CAM_ASSUME_CLAUDE_CONTRACT` overrides

## Context and Problem Statement

cam's interop surface is claude's credential write protocol: `wS()` path
resolution, `.credentials.json` schema, `.oauth_refresh.lock` /
`.storage-write` / `<realpath(storage)>.lock` coordination, and the scoped
login's env isolation. Bisecting the published linux-x64 artifacts (npm
`cli.js` bundles, then native binaries from `2.1.120` on) showed that
protocol is **version-banded, not universal**:

- `.oauth_refresh.lock` appears by `2.1.70`, `.storage-write` at `2.1.136`,
  `CLAUDE_SECURESTORAGE_CONFIG_DIR` (`wS()`) at `2.1.144`. The full
  contract exists together only from `2.1.144`; every sub-range below it
  lacks a different piece, so partial support cannot be stated.
- Bands drift internally: the refresh lock's staleness moved
  `stale:1e4` → `stale:60000,update:5000` between `2.1.150` and `2.1.218`,
  and `.design_oauth_refresh.lock` appeared at `2.1.218`. Patch releases
  change lock semantics — a newer version is not a compatible version.
- The launcher strip list of 6 vars was written against an early bundle;
  `2.1.288` reads credential-supply, endpoint-redirect, federation-store,
  and identity-injection vars that could silently skew or hijack a scoped
  login.

Before this decision only `cam add` enforced any floor (`1.0.0`, itself
wrong), and `switch`/`usage`/`auto` wrote credentials and consumed
one-time-use refresh tokens with no version check at all.

## Decision Drivers

- Never lose or clobber a credential lineage — a write under an
  unverified contract can persist something a live claude mangles, and a
  spent refresh token cannot be un-spent.
- Fail closed on what we have not measured; fail open on what we have.
- Reads race nothing: the credential/config file schema is version-stable
  across every band observed, so read-only commands must work with no
  claude installed at all.

## Considered Options

- Per-band behavior (different lock sets, probes per sub-range)
- Gate every command
- Gate at `cam` startup
- Gate at the narrowest unsafe op
- Floor `>=2.1.0`
- Override via CLI flag or persisted `cam config` key

## Decision Outcome

Chosen option: "Gate at the narrowest unsafe op", because probing only when about to mutate catches mid-session claude updates without charging every read a subprocess.

`shared/claude_contract.py` owns the band: `claude --version` → semver →
`[2.1.144, 2.2.0)`, else `UnsupportedClaudeVersionError`. The gate sits at
the narrowest unsafe operation, per use case: `SwitchAccount._transact`
top (before `.ops.lock`), `FetchAccountUsage`/`FreshenTarget` immediately
before `refresher.refresh()`, `ClaudeLoginLauncher` before spawn. Probe
failures (absent binary, unparseable banner, nonzero exit, timeout)
refuse — fail closed. `CAM_ASSUME_CLAUDE_CONTRACT` non-empty marks the
contract `assumed` and bypasses the band — explicit per-run, never
persisted. Read-only paths (`list`, `status`, `config`, `remove`,
`--dry-run`, cache-served or unexpired-credential usage, the active
account's usage) never probe.

The launcher environment doctrine (T6): the login child gets ambient env
minus every var that could redirect endpoints, supply credentials,
re-point the federation store, inject identity, or re-import env files —
the observed `2.1.288` literal set, grouped by hazard class in
`claude_login_launcher.py`. `CLAUDE_CONFIG_DIR` is still set explicitly to
the account dir (ADR-0004).

**Re-verification procedure** (run before bumping `SUPPORTED_MAX_EXCLUSIVE`
or the floor): fetch the candidate's linux-x64 artifact —
`npm pack @anthropic-ai/claude-code-linux-x64@<v>` (a tarball holding the
native binary; older bands ship `package/cli.js` under
`@anthropic-ai/claude-code` instead) — then grep the artifact for the
contract literals and compare semantics against the floor:

```
grep -ac SECURESTORAGE_CONFIG_DIR <artifact>   # wS() present? (≥1)
grep -ac storage-write <artifact>              # per-mutation lock (≥1)
grep -ac oauth_refresh <artifact>              # refresh lock family
grep -aoE 'stale:[0-9]+' <artifact>            # staleness drift check
<artifact> --version                           # X.Y.Z (Claude Code) shape
grep -ac 'claudeAiOauth\|expiresAt\|oauthAccount' <artifact>   # schema
grep -aoE '(ANTHROPIC|CLAUDE)_[A-Z_]+' <artifact> | sort -u    # env sweep
```

A bump is justified only when every literal is present, `wS()` semantics
and lock options match, and the env sweep adds nothing to the launcher's
hazard classes.

### Consequences

Mutating operations now cost one `claude --version` subprocess per call —
bounded (15s timeout), and never on read paths. A user on `claude >=2.2`
gets a refusal naming the exact override rather than silent divergence;
the env var is deliberately per-run so the override cannot fossilize. The
band edge is a constant, not config — widening it is a re-verification
commit, not a user decision. What a future reader may want to "fix": the
upper bound looks conservative while `2.2.x` does not exist yet — it is
the point: mid-band drift already happened once, and the cost of a false
positive is a clear error message while the cost of a false negative is a
stranded token lineage.

### Confirmation

The stub-version matrix in `test/unit/shared/test_claude_contract.py` exercises versions inside and outside the band plus the `CAM_ASSUME_CLAUDE_CONTRACT` override.

## Pros and Cons of the Options

| Option | Pro | Con |
| ------ | --- | --- |
| Per-band behavior (different lock sets, probes per sub-range) | Supports old claude | Each sub-range lacks a different contract subset — re-deriving per-band contracts is the unverified-band problem twice over, for zero users on ancient claude |
| Gate every command | Simplest rule | Breaks `list`/`status`/`config`/`remove` on machines with no claude; probes cost a subprocess per read |
| Gate at `cam` startup | One probe per invocation | A mid-session claude update slips through; TUI/long `auto` loops go stale |
| Gate at the narrowest unsafe op | Probe only when about to mutate; per-call probing catches updates at the next mutation, not next invocation | Probe is distributed across four call sites — needs a shared contract module to stay honest |
| Floor `>=2.1.0` | More permissive | `.storage-write`/CSSCD absent below 2.1.144 — interop claims would be false |
| Override via CLI flag or persisted `cam config` key | Discoverable | Flag needs plumbing per command; a persisted key silently outlives the mismatch it was set for |
