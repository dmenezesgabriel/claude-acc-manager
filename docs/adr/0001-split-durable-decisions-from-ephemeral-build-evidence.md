# ADR-0001 — Split durable decisions from ephemeral build evidence

Status: accepted
Date: 2026-10-01

## Context

This project builds by studying reference implementations (`research_repos/`, read-only and untracked) and porting their mechanisms. For its first milestones, `docs/plan.md` carried both the decisions and the porting evidence — `repo/path:line` citations frozen into a file meant to be permanent — plus milestone exit-gate measurements appended as dated blockquotes.

The failure mode was already visible, and the same one the `factory` repo measured before adopting this split (its ADR-0001): citations rot underneath the file, state recorded by accretion goes stale in place (the M4 User-Agent correction sat beside the claim it corrected), and the decisions are unfindable inside build instructions.

## Decision drivers

- A decision must stay readable after the code that motivated it changed.
- Build evidence is worth a great deal on the day it is used and nearly nothing afterwards; keeping it costs accuracy, because nobody re-verifies it.
- Every execution session re-reads this documentation, so its size is a running cost, not a one-time one.

## Options considered

| Option | Pro | Con |
| ------ | --- | --- |
| One growing plan document | Nothing to route between | What we had: rot, accretion, unfindable decisions |
| Spec-anchored docs beside the code | Specs stay true | Doubles the maintenance surface; the evidence still rots |
| Split by lifetime — durable decisions, ephemeral evidence | Each artifact is discarded or kept on its own merits | Requires the discipline to actually delete |

## Decision

Documents are separated by **lifetime**, not by topic.

**Durable** — `docs/adr/` and `docs/architecture.md`. These hold decisions and non-trivial knowledge. They cite real sources of truth: an endpoint's own contract, an upstream issue (`anthropics/claude-code#31021`), a published spec, a file in `src/`. They never cite `research_repos/`. The test: a durable document must still be true and useful if every reference implementation vanished.

**Ephemeral** — `docs/research/` and `docs/slices/`. Dense with reference citations, file paths, and measured comparisons. Deleted when their milestone or phase ships.

**Ledger** — `docs/backlog.md`. Edited in place, one line per row; gate results go in commit bodies.

When a milestone ships, its durable residue is an ADR (if a non-trivial decision was made) and code comments that state their _why_ without needing a link.

## Consequences

Reference implementations are construction scaffolding; their absence from the finished docs is the point, not an omission. Corrections are made by editing — git holds the diff, so a document never carries its own revision history inline.

The cost accepted: evidence for shipped work leaves the working tree. Recovering _why_ a mechanism looks the way it does means reading the ADR — if the ADR does not answer, the ADR was written badly; that is the failure mode to watch.

Code comments follow the same durable rule: they state a fact that stands alone, may cite an ADR or a real source of truth, and must not cite a planning doc. `research_repos/` mentions left over from the build phase are re-cited in a v1 sweep (backlog's deferred table).
