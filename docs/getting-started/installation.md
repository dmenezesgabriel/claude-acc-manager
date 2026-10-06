# Installation

## Requirements

- **Linux** — `cam` is Linux-only.
- **Claude Code** installed and signed in at least once — `cam` manages
  Claude Code's OAuth accounts, so it interoperates with the `claude`
  binary's on-disk layout rather than replacing it.
- A supported `claude` version — mutating commands (`add`, `switch`,
  `usage`, `auto`) verify the claude contract before touching anything and
  refuse outside the band `cam` was tested against. `cam doctor` reports
  what it found; `CAM_ASSUME_CLAUDE_CONTRACT` is the escape hatch (see
  [environment variables](../reference/environment-variables.md)).
- **Python ≥3.11** if you install into your own environment — the tool
  installers below handle the interpreter for you.

## Install

`cam` is a Python application distributed as a CLI tool — install it
isolated, not into a project venv:

```sh
uv tool install git+https://github.com/dmenezesgabriel/claude-acc-manager
# or
pipx install git+https://github.com/dmenezesgabriel/claude-acc-manager
```

Runtime dependencies are just `rich` and `textual`.

## Verify

```sh
cam doctor
```

`doctor` is a read-only diagnostic: it reports the resolved credential
paths, lock layout, environment overrides, and the claude contract probe —
findings never change the exit code, they are information for you.

Next: the [quickstart](quickstart.md) registers your first account.
