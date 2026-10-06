---
status: accepted
date: 2026-09-10
---

# ADR-0009 — Token ownership: never refresh the active slot; rotations persist atomically; `invalid_grant` quarantines

## Context and Problem Statement

Claude Code itself refreshes the credential sitting in `~/.claude/.credentials.json` whenever it needs to — it holds its own refresh lock for that purpose. Refresh tokens are **one-time use** (anthropics/claude-code#31021, #30930): every refresh returns a rotated pair and the previous refresh token dies immediately.

If `cam` also refreshed the *active* slot, two independent refreshes race on one lineage; the loser's persisted token is already dead, and the account unrecoverably logs out mid-session.

## Decision Drivers

- Exactly one refresher per lineage, ever.
- A rotation must be persisted atomically — access + refresh token in the same write — or a crash between them strands the lineage.
- `invalid_grant` is a permanent signal: the lineage is dead, not transiently failing.

## Considered Options

- cam refreshes whichever token is expired
- Active slot belongs to Claude Code; cam refreshes inactive accounts only, only when measurement requires

## Decision Outcome

Chosen option: "Active slot belongs to Claude Code; cam refreshes inactive accounts only, only when measurement requires", because exactly one refresher per lineage, ever.

The **active** account's tokens are refreshed by Claude Code alone — `cam` never refreshes the active slot. **Inactive** accounts are refreshed only when a measurement requires it (~hourly access-token expiry). A rotation is persisted in one atomic write (`persist_rotation`). `invalid_grant` marks the lineage dead and the account is quarantined from auto-pick; a failed rotation persist is a hard failure with re-login guidance.

### Consequences

`FetchAccountUsage` takes an explicit `is_active` flag: the active path must prove the refresher unreachable (the live integration test enforces this with fakes that raise if refresh runs). Registry `quarantined` lineages persist across runs — quarantine is durable state, not a runtime hint.

### Confirmation

Rollback under failure injection and `invalid_grant` quarantine are exercised in `test/unit/accounts/application/use_cases/test_switch_account.py` and `test_quarantine_dead_lineage.py`.

## Pros and Cons of the Options

| Option | Pro | Con |
| ------ | --- | --- |
| cam refreshes whichever token is expired | Uniform policy | Races Claude Code's own refresh on the active slot → stranded lineage |
| Active slot belongs to Claude Code; cam refreshes inactive accounts only, only when measurement requires | One refresher per lineage; matches observed safe practice | Inactive usage reads can hit an expired access token and must refresh-then-fetch (FetchAccountUsage already implements exactly this) |
