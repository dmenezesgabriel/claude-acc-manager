# ADR-0004 — Onboarding is login-at-source via `CLAUDE_CONFIG_DIR`

Status: accepted
Date: 2026-09-10

## Context

`cam add <name>` must produce an account whose OAuth tokens are valid and whose lineage stays valid over time. Claude Code isolates a whole profile via `CLAUDE_CONFIG_DIR`: a fresh login lands `.credentials.json` and `.claude.json` inside that directory (verified by probe: `claude 2.1.267`, 2026-09-10 — keys inspected, values never read).

Refresh tokens are **one-time use** (anthropics/claude-code#31021, #30930): a copied token's next rotation strands whichever copy was not refreshed. The documented operational rule for this model is "never run two clients against copies of the same refresh token."

## Decision drivers

- Eliminate the stranded-lineage failure mode by construction, not by care.
- `claude` must be the one performing the login — we never implement the OAuth handshake ourselves.

## Options considered

| Option | Pro | Con |
| ------ | --- | --- |
| Copy `~/.claude/.credentials.json` into the account slot | Simple; works with an existing login | Copies a one-time-use refresh token → lineage stranding on next rotation |
| `CLAUDE_CONFIG_DIR=<account dir>` + interactive `claude` login | Token lineage is born in the slot that owns it; nothing is ever copied | Requires the `claude` binary at add time; ambient credential env must be stripped so the prompt can't be skipped |

## Decision

`add` launches `claude` with `CLAUDE_CONFIG_DIR` pointing into `<store>/accounts/<name>/`; the login lands directly there. The captured `.credentials.json` and the `oauthAccount` section of `.claude.json` are read back by `AccountDirReaderPort` for registration; tokens never pass through copy operations.

## Consequences

Adding an account is interactive by construction — there is no headless `add`. A fresh login's `.credentials.json` contains only the `claudeAiOauth` key; the sibling `organizationUuid` seen on long-lived credentials is optional and treated as such by `ActiveSlotAdapter`. If Anthropic ever changes where a scoped login lands, the probe that established this (run `claude` in a scratch `CLAUDE_CONFIG_DIR`, inspect keys only) is the way to re-verify.

Re-probed at claude `2.1.287` (2026-10-03, strace): `CLAUDE_CONFIG_DIR` still isolates the plaintext credential store — the login itself is unchanged. Two bounds now apply, both enforced by `ClaudeLoginLauncher`: `CLAUDE_SECURESTORAGE_CONFIG_DIR` must be *stripped* from the child env because any defined value (empty included) overrides `CLAUDE_CONFIG_DIR` for the credential store, and claude `<1.0` is *refused* because it hardcodes `~/.claude/.credentials.json` and cannot isolate a scoped login at all ([ADR-0014](0014-credential-write-boundary.md)).
