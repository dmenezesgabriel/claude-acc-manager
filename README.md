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

- `docs/backlog.md` — milestone ledger; the entry point for an execution session.
- `docs/architecture.md` — why the system is shaped this way (arc42).
- `docs/adr/` — durable decisions (MADR).
- `AGENTS.md` — repo conventions and the docs map.

## Acknowledgments

Parts of the account-switching and usage-polling policy design were adapted
from [claude-swap](https://github.com/realiti4/claude-swap) (MIT License,
© Onur Cetinkol) — the anti-flap margins, event taxonomy, and poll-cadence
measurements — and the account model, dry-run switch capture, flat 429
backoff, and usage-response handling were informed by
[ai-usagebar](https://github.com/AkitaOnRails/ai-usagebar) (MIT License,
© AkitaOnRails). Both projects' MIT license terms apply to the adapted
portions; their copyright notices and permission notices are reproduced
below.

claude-swap — Copyright (c) 2026 Onur Cetinkol; ai-usagebar — Copyright (c)
2026 AkitaOnRails:

> Permission is hereby granted, free of charge, to any person obtaining a
> copy of this software and associated documentation files (the
> "Software"), to deal in the Software without restriction, including
> without limitation the rights to use, copy, modify, merge, publish,
> distribute, sublicense, and/or sell copies of the Software, and to permit
> persons to whom the Software is furnished to do so, subject to the
> following conditions:
>
> The above copyright notice and this permission notice shall be included
> in all copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
> OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
> MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN
> NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
> DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
> OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE
> USE OR OTHER DEALINGS IN THE SOFTWARE.
