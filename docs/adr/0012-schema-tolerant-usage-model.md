---
status: accepted
date: 2026-09-10
---

# ADR-0012 — Schema-tolerant usage model: `five_hour`, `seven_day`, scoped `limits[]`; `extra_usage` deferred

## Context and Problem Statement

`GET /api/oauth/usage` is undocumented and can drift — upstream has open feature requests for an official surface (anthropics/claude-code#44328, #32796). The observed response carries `five_hour`, `seven_day`, `seven_day_sonnet`, `seven_day_opus`, `extra_usage`, and a `limits[]` array whose entries may carry `scope.model.display_name`. Unknown top-level keys exist in the wild (a `tangelo: null` key has been observed).

Two facts discipline the model: per-model weekly windows arrive **only** through `limits[]` entries carrying `scope.model.display_name` — `seven_day_sonnet`/`_opus` are *not* a reliable model axis (independent implementations don't model them; the fixture evidence smuggles unknown keys precisely to prove tolerance). And `extra_usage` (pay-as-you-go credits) is a separate axis no milestone consumes.

## Decision Drivers

- Missing or renamed windows must degrade to "unknown", never crash a quota read.
- Model-scoped weeklies must key on the *shape* (`scope.model.display_name`), never on `limits[].kind` values that can be renamed.
- No speculative fields: parse what a consumer uses.

## Considered Options

- Model every observed key (`seven_day_sonnet`, `seven_day_opus`, `extra_usage`, …)
- Parse `five_hour` + `seven_day` + scoped `limits[]`; tolerate all other keys

## Decision Outcome

Chosen option: "Parse `five_hour` + `seven_day` + scoped `limits[]`; tolerate all other keys", because it matches how both independent reference parsers actually behave, and drift surfaces via the `-m integration` smoke instead of guessed fields.

`usage_snapshot_from_response` models exactly `five_hour`, `seven_day`, and each `limits[]` window carrying `scope.model.display_name`; a missing window is `None`, not an error; every other key is tolerated and ignored. `extra_usage` stays unparsed until a real consumer exists (backlog's deferred table owns it).

### Consequences

Utilization/`percent` are 0–100 floats; ≤101 accepted (rounding slack) and saturated to 100. If Anthropic ships an official usage endpoint or a new window kind that matters (e.g. a distinct Opus weekly), the parse surface is one pure function — extend it with a consumer in hand, not preemptively.

## Pros and Cons of the Options

| Option | Pro | Con |
| ------ | --- | --- |
| Model every observed key (`seven_day_sonnet`, `seven_day_opus`, `extra_usage`, …) | Complete coverage of today's wire shape | Couples to keys already proven unreliable; `extra_usage` has no consumer |
| Parse `five_hour` + `seven_day` + scoped `limits[]`; tolerate all other keys | Matches how both independent parsers actually behave; drift surfaces via the `-m integration` smoke test | `extra_usage` data is discarded until needed |

## More Information

- Corrects an earlier over-modelled reading of the response.
