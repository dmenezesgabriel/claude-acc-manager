# Diagnostics

## `cam doctor`

Read-only health check for cam's claude interop — resolved credential
paths, the lock layout, environment overrides in effect, and the claude
contract probe. Findings are informational: `doctor` never changes its
exit code over what it reports.

```sh
cam doctor
```

Reach for it first when a mutating command refuses or behaves unexpectedly.

## Common findings

**Contract refusal** — `add`, `switch`, `usage`, and `auto` verify the
claude version before touching its files. Outside the tested band they
refuse (`UnsupportedClaudeVersion` under `--json`). If you've verified a
newer claude yourself, `CAM_ASSUME_CLAUDE_CONTRACT=1` bypasses the gate —
see [environment variables](../reference/environment-variables.md).

**Lock timeouts** — `TimeoutError` means a lock bound was exceeded: another
cam operation or claude itself is mid-write. Retry shortly; if it persists,
`cam doctor` shows which lock path is held.

**Quarantined account** — Anthropic answered `invalid_grant`; the refresh
lineage is dead. The account drops out of automatic switching until you
re-register it: `cam add <name>` with the same name.

**Stale usage / `usageRetryAt`** — a 429 armed the rate-limit backoff; the
last-good snapshot is served until the backoff window passes. Nothing to
fix — the retry timestamp is in the JSON payload.

**Unmanaged live login** — claude is signed into an account outside cam's
registry; see [switching](switching.md) for what that means.

## Display problems

Human output degrades instead of breaking: `NO_COLOR` kills color, piping
to a file strips formatting, and `TERM=dumb` marks the terminal
non-interactive — bare `cam` then prints usage instead of opening the TUI.
`--json` output is unaffected by all of it.

Running as root outside a container is refused outright — credential writes
under a root-owned XDG path are never correct.
