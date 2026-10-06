# Switching accounts

## Switch by name

```sh
cam switch personal
```

The switch is a transaction — the registry's active pointer, the credential
files, and the `.claude.json` splice move together or roll back together; a
half-applied state is never left behind. The splice preserves every
unrelated key in `.claude.json` — only the account identity is replaced.

Disabled and quarantined accounts stay valid explicit targets — `cam switch
<name>` is you telling cam exactly what you want; the eligibility filter
only gates *automatic* picks.

## Let a strategy pick

Omit the name and a strategy chooses from cached usage:

```sh
cam switch --strategy best            # default
cam switch --strategy next-available
```

- **`best`** lands only on an account with *strictly* more headroom than
  the current one — ties stay put, and if the current account's usage
  can't be measured nothing is provably better, so cam stays
  (`usage-unavailable`).
- **`next-available`** walks the registry past the current account and
  takes the first eligible candidate — a measured candidate at 0 headroom
  is skipped (`at-limit`), an unmeasured one is not.

Disabled, quarantined, and credential-less accounts are skipped by both
strategies and reported in the `skipped` list. When nothing is eligible
the outcome is `no-valid-target` — or `candidates-exhausted` if at least
one account exists but everything measured is at the wall.

## Preview before committing

```sh
cam switch --dry-run
```

Reports the target, the skipped candidates, and what would be preserved —
without touching a byte.

## Keep an account out of rotation

```sh
cam disable personal   # still a valid explicit target
cam enable personal    # back in the pool
```

## Unmanaged live logins

If the active `claude` login isn't one cam knows (signed in before cam
existed, or into a different profile), `cam status` reports it as
unmanaged. Strategy switches from an unmanaged login can't compare
headroom — `best` reports `usage-unavailable`; name the target explicitly,
or register the live login as an account first.
