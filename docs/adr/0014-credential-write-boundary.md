---
status: accepted
date: 2026-10-03
---

# ADR-0014 — Credential writes mirror claude's `.storage-write`; cam serializes itself with `.ops.lock`

## Context and Problem Statement

A `cam add` racing a `cam switch` (TUI or `cam auto`) corrupted the login
capture: the switch moved the account's `.credentials.json` into the live
slot while the add's `claude` was still inside its OAuth login, and the
add's read-back reported the login as unfinished. Two further gaps surfaced
while re-verifying claude's storage contract on 2.1.287 (Linux):

- claude 2.1.x holds `<storage>/.storage-write` (proper-lockfile, 15s
  staleness) around every credential mutation — cam held nothing there, so
  our writes could interleave with a live claude's refresh mutations.
- The storage dir resolves via `CLAUDE_SECURESTORAGE_CONFIG_DIR` (a defined
  value — including empty, which forces `~/.claude` — wins over
  `CLAUDE_CONFIG_DIR`). cam resolved live paths and lock dirs through
  `CLAUDE_CONFIG_DIR` only, so an exported variable silently split our view
  from claude's actual store. The login launcher also leaked it to the
  child, defeating the account-dir isolation (ADR-0004).
- On Linux the secure-storage layer has exactly one backend — the plaintext
  file; keychain legs exist only for macOS and Windows.

## Decision Drivers

- Never lose or clobber a credential lineage — the move model's invariant.
- Interop with claude's own write protocol rather than inventing one.
- Minimum mechanism: no lock types beyond what the evidence requires.

## Considered Options

- `.storage-write` per mutation, inside the file adapters
- `.storage-write` held transaction-wide
- Store-wide `flock` (`.ops.lock`) on add/remove/switch
- Per-account-dir locks
- Strip `CLAUDE_SECURESTORAGE_CONFIG_DIR` in the launcher
- Export `CSSCD=<account dir>` instead

## Decision Outcome

Chosen option: "`.storage-write` per mutation inside the file adapters + store-wide `.ops.lock` on add/remove/switch + strip `CLAUDE_SECURESTORAGE_CONFIG_DIR` in the launcher", because it mirrors upstream granularity for credential writes, serializes cam-vs-cam transactions without reentrancy deadlock, and keeps the keychain-name hash suffix.

`path_resolver.secure_storage_home` mirrors claude's resolution
(`CSSCD` defined → verbatim, defined-empty → `~/.claude`, absent →
`CLAUDE_CONFIG_DIR || ~/.claude`); the live credentials path and both
credential-lock dirs derive from it. Every `.credentials.json` mutation in
the file adapters holds `.storage-write`. `AddAccount`, `RemoveAccount`,
and `SwitchAccount._transact` hold `FlockOpsLock` (`<store>/.ops.lock`,
exclusive flock) — outermost, before claude's locks. The launcher strips
`CSSCD` and refuses claude <1.0 (its credential path is hardcoded
`~/.claude`, so a scoped login cannot isolate).

### Consequences

A switch attempted during an interactive `cam add` now waits, then fails
cleanly with `TimeoutError` — safe, and visible instead of corrupting.
`persist_rotation` deliberately holds only `.storage-write`: gating it on
`.ops.lock` would stall usage refresh behind a login, and its worst case
(resurrected parked file) is contained by the `_is_live` guard and
quarantine. If claude adds a Linux keychain leg in a future version, this
boundary is where its resolution and mutation locks get mirrored.

## Pros and Cons of the Options

| Option | Pro | Con |
| ------ | --- | --- |
| `.storage-write` per mutation, inside the file adapters | Mirrors upstream granularity; readers and long operations never wait | More acquisitions than one transaction-level hold |
| `.storage-write` held transaction-wide | Fewer acquisitions | Deadlock: our mkdir locks are not reentrant, and nested adapter writes would self-block |
| Store-wide `flock` (`.ops.lock`) on add/remove/switch | One file, same mechanism as the registry `.lock`; covers every cam-vs-cam account-dir mutation | A long interactive add blocks a concurrent switch — which is exactly the interleaving that caused the defect |
| Per-account-dir locks | Finer concurrency | Switch mutates two dirs + live slot → multi-lock ordering rules needed; more code, same guarantee |
| Strip `CLAUDE_SECURESTORAGE_CONFIG_DIR` in the launcher | `CLAUDE_CONFIG_DIR` alone isolates both backends; keeps the keychain-name hash suffix | None identified |
| Export `CSSCD=<account dir>` instead | Also redirects the store | Removes the per-dir keychain-name hash → item name collides with the default login; redundant for the file backend |
