# ADR-0008 — A 429 arms a flat backoff; last-good is served while trust holds

Status: accepted
Date: 2026-09-11 (user decision among presented options)

## Context

When `/api/oauth/usage` answers 429, two response models were available from measured evidence:

- **Retry-After-derived backoff** — parse `Retry-After`, sleep that long. But this endpoint's header is documented unreliable: `retry-after: 0` while still limited (#30930), and a 30→60→120→240→300s retry ladder that never recovers (#31637).
- **Flat lockout** — one constant backoff window, serve frozen last-good data meanwhile.

A cached last-good snapshot is trustworthy until its limiting window's own reset epoch passes — after that the snapshot is obsolete regardless of the error that froze it.

## Decision drivers

- Never derive timing from a header this endpoint has proven to lie about.
- 429 means *throttled*, never *exhausted* — the account's quota state is unknowable during the backoff, so decisions must not consume a fake "0%".

## Options considered

| Option | Pro | Con |
| ------ | --- | --- |
| Honor `Retry-After` per response | Adaptive when the header is honest | Demonstrably dishonest here; couples our cadence to a broken signal |
| Flat `RATE_LIMIT_BACKOFF_S` lockout + `trust_ok` gate on last-good | Deterministic; matches the measured wall; simple to test | Cruder — same backoff regardless of cause |

## Decision

A 429 arms a flat backoff (`usage/domain/usage_cache_entry.py`, `cache_trust.py`) and serves the frozen last-good snapshot while `trust_ok` holds — i.e. until the limiting window's earliest reset epoch passes (the unfiltered `earliest_reset_epoch`; the future-filtered variant is only for capping the next poll time). Every other fetch failure freezes last-good the same way without arming the lockout.

## Consequences

`trust_ok`'s correctness is subtle enough to have already produced one defect (future-filtered helper used for the trust check — a window whose reset had passed silently fell back to age-only trust); the regression test pins the split. A caller reaching for "earliest reset" must pick the helper for the job: unfiltered for trust, future-filtered for scheduling.
