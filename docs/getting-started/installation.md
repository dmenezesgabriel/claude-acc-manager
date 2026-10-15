# Installation

## Requirements

- Linux. `cam` runs on Linux only.
- Claude Code installed and signed in at least once. `cam` manages
  Claude Code's OAuth accounts, so it interoperates with the `claude`
  binary's on-disk layout rather than replacing it.
- A supported `claude` version. Mutating commands (`add`, `switch`,
  `usage`, `auto`) verify the claude contract before touching anything and
  refuse outside the band `cam` was tested against. `cam doctor` reports
  what it found; `CAM_ASSUME_CLAUDE_CONTRACT` is the escape hatch (see
  [environment variables](../reference/environment-variables.md)).
- Python ≥3.11 if you install into your own environment. The tool
  installers below handle the interpreter for you.

## Install

`cam` is a Python application distributed as a CLI tool; install it
isolated, not into a project venv:

```sh
uv tool install claude-acc-manager
# or
pipx install claude-acc-manager
```

From source instead (for a checkout or a PR):

```sh
uv tool install git+https://github.com/dmenezesgabriel/claude-acc-manager
```

Runtime dependencies are `rich` and `textual`.

Upgrades run through [`cam upgrade`](../reference/cli.md#self-update),
which delegates back to the installer; a source install instead prints
the re-install command for you.

## Verify

```sh
cam doctor
```

`doctor` is a read-only diagnostic: it reports the resolved credential
paths, lock layout, environment overrides, and the claude contract probe.
Findings never change the exit code; they are information for you.

Next: the [quickstart](quickstart.md) registers your first account.
