# claude-acc-manager (`cam`)

Linux-only CLI/TUI to manage, measure, and swap Claude Code OAuth
subscription accounts.

`cam` keeps a registry of Claude Code logins, measures each account's quota
usage against Anthropic's OAuth usage endpoint, and swaps the live `claude`
login to the account with the most headroom, on demand or unattended via a
polling loop. Credentials live as `0600`/`0700` files under XDG paths with
atomic writes and proper-lockfile-compatible mkdir locks.

```{.cam path="maintainer/docs-shots/dashboard.py" columns=110 lines=30}
```

## Where to start

- [Getting started](getting-started/installation.md): install `cam`,
  register your first account, and open the dashboard.
- [Guides](guides/switching.md): task recipes for switching strategies, the
  `auto` loop, `--json` scripting, and diagnostics.
- [Reference](reference/cli.md): the command-by-command CLI surface, the
  schema-v1 JSON contract, `settings.json` keys, and environment variables.
- [Internals](architecture.md): why the system is shaped this way, in the
  arc42 architecture document and the ADR record.

## What `cam` is not

OAuth subscription accounts only; API-key and setup-token accounts are out
of scope. Linux only; there is no macOS keychain, menubar, or Claude
Desktop integration. The full scope list lives in `architecture.md` §11.
