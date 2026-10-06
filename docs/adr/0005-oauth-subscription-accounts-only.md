---
status: accepted
date: 2026-09-10
---

# ADR-0005 — OAuth subscription accounts only

## Context and Problem Statement

`cam` exists to measure and swap accounts by *quota*. The usage endpoint `GET /api/oauth/usage` answers only for OAuth subscription credentials — API keys are rejected 401.

## Decision Drivers

- Every feature (usage display, headroom ranking, threshold auto-switching) presumes measurable quota windows.
- Supporting API-key accounts would add an account kind that cannot be measured — a second-class citizen in every strategy.

## Considered Options

- OAuth subscription accounts only
- Also accept API keys / setup tokens

## Decision Outcome

Chosen option: "OAuth subscription accounts only", because every feature presumes measurable quota windows.

Only OAuth subscription accounts are registered. `add` goes through the `claude` OAuth login (ADR-0004); there is no API-key path.

### Consequences

API-key and setup-token accounts are an explicit v1 non-goal. If Anthropic ever exposes usage for other credential types, this ADR is the thing to revisit — the gating fact is measurability, not the credential format.

## Pros and Cons of the Options

| Option | Pro | Con |
| ------ | --- | --- |
| OAuth subscription accounts only | One credential shape; every account is measurable | Users of API-key billing are out of scope |
| Also accept API keys / setup tokens | Wider coverage | Unmeasurable accounts break the strategy contract; more auth surface to secure |
