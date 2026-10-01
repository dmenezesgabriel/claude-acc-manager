# ADR-0003 — Credentials at rest: 0600 files / 0700 dirs under XDG, atomic writes

Status: accepted
Date: 2026-09-10

## Context

Per-account OAuth blobs and the registry must persist on disk. Claude Code itself stores OAuth credentials as a 0600 file (`~/.claude/.credentials.json` on Linux), so the filesystem model is what the ecosystem already practices.

## Decision drivers

- Linux-only scope (non-goal: macOS keychain).
- No dbus/Secret Service dependency for a tool that must run in minimal environments.
- A torn write must never leave a partial credential or registry — multi-process safety needs atomic rename + flock.

## Options considered

| Option | Pro | Con |
| ------ | --- | --- |
| Secret Service / dbus keyring | OS-managed secret store | dbus dependency; headless hosts often lack a running service; over-scope for v1 |
| `keyring` library | One API over backends | Runtime dep + backend variance; same over-scope |
| 0600/0700 files under `$XDG_DATA_HOME/claude-acc-manager`, atomic tmp+rename | Matches Claude Code's own model; zero deps; fully testable under tmp-HOME | We own mode enforcement and atomicity discipline |

## Decision

All state lives under `$XDG_DATA_HOME/claude-acc-manager` (default `~/.local/share/claude-acc-manager`): `accounts/<name>/` dirs (each a real `CLAUDE_CONFIG_DIR`), `registry.json`, `usage-cache.json`, `settings.json`, and a single `.lock` flock. Dirs are 0700, files 0600, every write is atomic tmp+rename through `src/claude_acc_manager/shared/fsio.py` — the single implementation. Secret Service can be added later behind the storage port without changing the use cases.

## Consequences

Mode enforcement and atomicity are centralized — a unit test asserts them on every credential write path, so a second write path must go through fsio, not around it. `ensure_private_dir` tightens only directories it creates: an earlier defect chmod'd the first *existing* ancestor (would have made `~/.local/share` 0700); the regression test pins the corrected walk.
