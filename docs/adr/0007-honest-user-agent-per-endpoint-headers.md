# ADR-0007 — Honest `User-Agent`; header sets are per-endpoint, not uniform

Status: accepted
Date: 2026-09-10 (corrects the originally recorded "spoof claude-code" assumption)

## Context

`GET /api/oauth/usage` rate-limits by User-Agent bucket. The measured facts:

- No `User-Agent` at all → 429; `User-Agent: claude-code/2.1.72` → 200 on the same token at the same moment (anthropics/claude-code#31021).
- A **non-empty custom** UA also works, but lands in a smaller *non-first-party* budget: ~28–30 requests/hour/identity measured for third-party pollers; aggressive 30–60s polling hits a 429 wall that does not recover (anthropics/claude-code#31637).
- Our polling constants (`poll_policy`: ~1 req/3min average, 180s floors, ±10% jitter) were calibrated **under the non-first-party regime** — they are only valid if we stay in that bucket.

## Decision drivers

- The measured polling budget must match the bucket we actually occupy, or the numbers are fiction.
- Honesty: a tool managing Claude accounts should identify itself, not impersonate the first-party client.
- A real 403/429 incident was fixed upstream (in one reference) by adding *a* UA — the load-bearing property is non-empty and stable, not the `claude-code` string.

## Options considered

| Option | Pro | Con |
| ------ | --- | --- |
| Spoof `claude-code/<version>` | First-party budget (more headroom) | Misidentifies the client; the calibrated budget wouldn't apply anyway; a tightening of the check would hit us harder |
| Honest `claude-acc-manager/<version>` | Matches the measured non-first-party budget; self-identifying; live-verified 200 (M4 smoke, `-m integration`) | Fewer requests/hour available — already priced into poll_policy |

## Decision

Every request sends `User-Agent: claude-acc-manager/<version>` — one constant in `src/claude_acc_manager/usage/infrastructure/anthropic_oauth.py`.

Header sets are **per-endpoint**, matching observed working clients: usage GET sends `Authorization` + `anthropic-beta: oauth-2025-04-20` + UA and no `Content-Type`; refresh POST sends `Content-Type: application/json` + UA and no `anthropic-beta`; profile GET matches usage GET. No uniform header bag.

## Consequences

The thing a future reader will be tempted to "fix": the modest request budget. Do not raise polling frequency toward first-party assumptions — the budget is the non-first-party one, and the wall (#31637) does not recover. If Anthropic tightens UA checks, the single point of change is the UA constant.
