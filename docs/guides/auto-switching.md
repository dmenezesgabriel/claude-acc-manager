# Automatic switching

`cam auto` is a foreground loop that watches the active account and swaps
the live login before a quota window walls you.

```sh
cam auto              # loop until SIGTERM (clean shutdown)
cam auto --once       # one evaluation; outcome in the exit code
cam auto --dry-run    # decide and report, switch nothing
```

## What a tick does

Each tick refreshes usage through the throttled poll policy, classifies the
active account's headroom against `autoswitch.threshold`, and acts:

- **below threshold** — stay put.
- **proactive** — threshold crossed: escape *before* the wall, but only to
  a target that clears the anti-flap gates (hysteresis margin, no-return
  guard, cooldown).
- **at-limit** — headroom hit zero: escape now; the anti-flap gates stand
  down, an exhausted candidate is better than a full one.

The engine never switches back to the account it just left until that
account has genuinely recovered — the "no-return" guard is what stops a
two-account ping-pong. Unknown usage is never treated as exhausted: an
unmeasurable active account maps to no-action, not failover.

## Tuning

Knobs live in `settings.json` and are overridable per run via flags —
see the [settings reference](../reference/settings.md):

| Flag | Key | Default |
| --- | --- | --- |
| `--threshold` | `autoswitch.threshold` | 90 |
| `--interval` | `autoswitch.intervalSeconds` | 60 |
| `--cooldown` | `autoswitch.cooldownSeconds` | 300 |
| `--strategy` | `autoswitch.strategy` | `best` |

Near the threshold the poll interval tightens to a minute (urgent mode);
a recent 429 suppresses it and grows the interval instead.

## `--once` exit codes

| Code | Meaning |
| --- | --- |
| `0` | evaluated and switched |
| `1` | error during evaluation |
| `2` | evaluated, no action needed |
| `3` | wanted to switch but blocked — cooldown, quarantined target, or all candidates exhausted |

`--once` is the shape a cron entry or systemd timer drives — the foreground
loop itself is deliberately not packaged as a service (run it under your
own supervisor if you want one).

## Quarantine

When Anthropic answers a refresh with `invalid_grant` the lineage is dead —
refresh-token rotation means a replayed token has no second chance. cam
quarantines the account instead of retrying: it drops out of every
automatic pick (visible in `cam list` and `cam status`), and the only fix
is a fresh login — `cam add <name>` with the same name re-registers and
clears the quarantine.

## JSONL event stream

`cam auto --json` emits one JSON object per line (`poll`, `switch`,
`no_switch`, `quarantined`, `all_exhausted`, `sleep`, `error`) — the schema
is in the [JSON output reference](../reference/json-output.md).
