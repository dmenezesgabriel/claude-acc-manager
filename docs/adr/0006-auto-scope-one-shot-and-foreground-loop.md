# ADR-0006 — Auto scope: one-shot strategies + `auto --once` + foreground loop; no systemd packaging

Status: accepted
Date: 2026-09-10

## Context

Unattended switching needs *some* scheduler. The question was how much process supervision to own in v1.

## Decision drivers

- Cover the three real usages: manual (`switch`), scripted (`auto --once`, meaningful exit codes), unattended (`auto` foreground loop).
- A correctly-supervised foreground loop is already systemd-runnable by the user — packaging our own unit adds a distribution concern without adding capability.

## Options considered

| Option | Pro | Con |
| ------ | --- | --- |
| `auto` foreground loop + `--once` tick | Simplest thing that covers manual/scripted/unattended; SIGTERM-clean contract is ours to keep | User wires their own supervision |
| Ship a systemd user unit | Zero user wiring | Packaging surface, distro variance, install/upgrade machinery — for a loop a unit file wraps in 5 lines |
| cron/systemd-timer only | No daemon at all | Loses the loop's statefulness (cooldown, backoff) across runs without extra persistence work |

## Decision

v1 ships `--strategy` on `switch`, `auto --once` (exit 0 switched / 1 error / 2 no action / 3 blocked — a wrapper pages on blocked: wanted to switch but no viable target or the fleet is exhausted), and `auto` as a SIGTERM-clean foreground loop (default 60s interval, min 15s; threshold default 90%; cooldown 300s). systemd packaging is a non-goal.

## Consequences

The loop must behave like a good foreground citizen — clean SIGTERM, no orphan state — precisely because supervision is delegated. If packaged units are ever wanted, they wrap `auto` unchanged; nothing in the loop may assume it owns the terminal.
