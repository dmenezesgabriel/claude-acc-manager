# Quickstart

Five minutes from install to a live dashboard.

## 1. Register an account

```sh
cam add work
```

`cam` launches `claude login` with an isolated `CLAUDE_CONFIG_DIR` — the
OAuth flow runs in your browser exactly as it does for Claude Code itself,
but the resulting credentials land in `cam`'s registry instead of your live
`~/.claude` slot. No token is ever copied: the account is logged in *at the
source*.

Repeat for each account (`cam add personal`, …).

## 2. See what you have

```sh
cam list      # registered accounts, which is live, enabled flags
cam status    # which account the live claude slot currently uses
cam usage work
```

`cam usage` reads the OAuth usage endpoint and caches the result — quota
windows only move on claude traffic, so repeated calls are served from the
last-good cache rather than re-hitting the API.

## 3. Switch the live login

```sh
cam switch personal   # by name
cam switch            # or let a strategy pick the best headroom
```

The switch is a transaction: the registry pointer, the credential files,
and the `.claude.json` splice move together or roll back together.

## 4. Watch it live

```sh
cam          # no subcommand opens the TUI on a terminal
cam tui      # explicit
```

The dashboard shows every account's 5-hour and 7-day windows and refreshes
through the same throttled path as the CLI. Press ++f1++ for the key help
panel.

## 5. Automate it (optional)

```sh
cam auto --once    # evaluate once: switch if an account beats the active one
cam auto           # foreground polling loop, SIGTERM-clean
```

Tuning lives in `settings.json` — see the
[auto-switching guide](../guides/auto-switching.md) and the
[settings reference](../reference/settings.md).
