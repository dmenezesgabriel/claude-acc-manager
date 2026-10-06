# claude-acc-manager (`cam`)

Linux-only CLI/TUI to manage, measure, and swap Claude Code OAuth subscription accounts.

`cam` keeps a registry of Claude Code logins, measures each account's quota usage
against Anthropic's OAuth usage endpoint, and swaps the live `claude` login to the
account with the most headroom — on demand, or unattended via a polling loop.
Credentials live as `0600`/`0700` files under XDG paths with atomic writes and
proper-lockfile-compatible mkdir locks.

## Install

Requires Python ≥3.11. Runtime deps: `rich`, `textual`.

```sh
uv tool install .
# or
pipx install .
```

## Commands

| Command | Does |
| --- | --- |
| `cam add <name>` | register an account via an isolated `claude login` |
| `cam remove <name>` | unregister an account and delete its login dir |
| `cam list [--json]` | list registered accounts |
| `cam status [--json]` | show the account the live claude slot uses |
| `cam usage <name> [--json]` | show one account's quota usage |
| `cam switch [name] [--strategy best\|next-available] [--dry-run] [--json]` | move the live login to another account; omit `name` to rotate by strategy |
| `cam enable <name>` / `cam disable <name>` | include/exclude an account from automatic switching |
| `cam auto [--once] [--interval S] [--threshold PCT] [--cooldown S] [--strategy S] [--dry-run] [--json]` | auto-switch loop; `--once` reports the outcome via exit code (0 switched, 1 error, 2 no action, 3 blocked) |
| `cam tui` | interactive quota dashboard |
| `cam doctor` | diagnose cam's claude interop setup (paths, locks, env, contract band) |
| `cam watch` | interactive live monitor |
| `cam config [list\|get\|set\|unset\|path]` | view or edit persisted settings (`settings.json`) |
| `cam --version` | print the installed cam version |

`cam` with no subcommand opens the TUI on an interactive terminal, prints
usage otherwise. `--json` output is schema-v1 stable; human output
degrades gracefully under `NO_COLOR`, `TERM=dumb`, or a pipe.

## Docs

- `maintainer/backlog.md` — milestone ledger; the entry point for an execution session.
- `docs/architecture.md` — why the system is shaped this way (arc42).
- `docs/adr/` — durable decisions (MADR).
- `AGENTS.md` — repo conventions and the docs map.

## Acknowledgments

Design informed by [claude-swap](https://github.com/realiti4/claude-swap)
and [ai-usagebar](https://github.com/AkitaOnRails/ai-usagebar) — both MIT.
See [NOTICE](NOTICE).
