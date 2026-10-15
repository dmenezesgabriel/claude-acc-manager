# CLI reference

`cam` is one command with subcommands. `cam` with no subcommand opens
the TUI on an interactive terminal and prints usage otherwise.

Every command accepts `-h`/`--help`. Mutating commands (`add`, `switch`,
`usage`, `auto`) verify the claude contract before acting; read-only
commands (`list`, `status`, `doctor`, `config`) are ungated, as is
`upgrade`, which touches no claude files.

## Account management

| Command | Does |
| --- | --- |
| `cam add <name>` | Register an account: launches `claude login` with an isolated `CLAUDE_CONFIG_DIR` so the OAuth flow lands in cam's registry |
| `cam remove <name>` | Unregister an account and delete its login dir |
| `cam list [--json]` | List accounts: active marker, enabled flag, quarantine flag, cached usage |
| `cam status [--json]` | Show which account the live claude slot uses (managed or unmanaged) |
| `cam enable <name>` / `cam disable <name>` | Include/exclude an account from strategy-driven and auto switching |

## Switching

```text
cam switch [name] [--strategy best|next-available] [--dry-run] [--json] [--model MODEL]
```

Omit `name` to rotate by strategy (default `best`: the enabled account
with the most headroom that strictly beats the active one).
`--dry-run` describes the switch (target, skipped candidates, preserved
files) without applying it.

## Usage

```text
cam usage <name> [--json]
```

Fetches one account's 5-hour and 7-day utilization plus scoped per-model
weeklies from the OAuth usage endpoint. A fresh cached reading is served
instead of re-fetching; a 429 arms a flat backoff and the last-good
snapshot is served while trust holds.

## Auto-switching

```text
cam auto [--once] [--interval S] [--threshold PCT] [--cooldown S] [--strategy S] [--dry-run] [--json]
```

Foreground polling loop; `--once` evaluates a single tick and reports the
outcome via exit code. Flag values override `settings.json` for this run.
`--json` emits one JSON event per line.

## Interactive

| Command | Does |
| --- | --- |
| `cam tui` | Quota dashboard: all accounts, both windows, key-driven switching (`F1` help) |
| `cam watch` | Live monitor view |

`cam watch` (or `w` inside `cam tui`) streams the refresh loop live:

```{.cam path="maintainer/docs-shots/dashboard.py" columns=100 lines=34 press="w,wait:400"}
```

## Diagnostics & settings

| Command | Does |
| --- | --- |
| `cam doctor` | Read-only diagnostic of cam's claude interop: resolved paths, lock layout, env overrides, contract probe. Findings never gate the exit code |
| `cam config list [--json]` | Every setting's effective value |
| `cam config get <key> [--json]` | One setting's effective value; bare output scripts cleanly |
| `cam config set <key> <value>` | Validate and persist one setting (strict parse; bad input fails loudly) |
| `cam config unset <key>` | Revert one setting to its default |
| `cam config path` | Print the `settings.json` location |
| `cam --version` | Print the installed cam version |

## Self-update

```text
cam upgrade [target]
```

`cam upgrade` upgrades cam by delegating to the installer that put it
here (`uv tool upgrade` / `pipx upgrade`), inheriting the terminal and
returning the manager's exit code; cam never edits its own files.
`[target]` pins `claude-acc-manager==<target>` under uv; `pipx upgrade`
takes no specifier, so a pipx pin prints the `pipx install --force`
step instead. Source checkouts (`git`/`path` installs) and installs cam
can't identify print their manual upgrade path and exit 1.

After other commands, a newer PyPI release prints a one-line notice on
**stderr**; stdout and `--json` stay clean. `auto`, `tui`, `watch`, and
`upgrade` are skipped: they carry their own update surfaces (the
`update-available` event line, the mount toast, the remedy itself).
`updates.mode` controls the mechanism (`off` silences every surface);
`CAM_DISABLE_UPDATE_CHECK` kills it regardless. Under
`updates.mode=auto`, a patch release is applied at the notice hook;
minor and major releases still only notify.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success; under `auto --once`: a switch happened |
| `1` | Handled failure: unknown account, refused login, lock timeout, contract refusal; `error:` on stderr, or the schema-v1 error envelope on stdout under `--json` |
| `2` | Usage error (argparse); under `auto --once`: evaluated, no action needed |
| `3` | `auto --once` evaluated but was blocked (cooldown, quarantine, all exhausted) |
| `130` | Interrupted by Ctrl-C |

Running as root outside a container is refused before dispatch (`exit 1`,
`RootRefused` in the JSON envelope).
