---
# Upstream MADR fields we keep: status + date. decision-makers/consulted/
# informed are omitted — solo maintainer.
status: proposed | accepted | superseded by ADR-NNNN
date: YYYY-MM-DD
---

# ADR-0000 — Title in the imperative

## Context and Problem Statement

The forces at play, in terms of **this system**. What made a decision necessary, what constraints bound it, what we knew at the time.

A reader must be able to follow this without access to any reference repository. Cite real sources of truth — an endpoint's own contract, an upstream issue, a published spec, a file in `src/`. Never cite `research_repos/`: those are construction scaffolding, and scaffolding comes down. Build evidence belongs in the slice or research doc that consumed it.

## Decision Drivers

- What we were optimising for, most important first.

## Considered Options

- Option title
- …

## Decision Outcome

Chosen option: "option title", because the reasoning in one sentence.

### Consequences

What this makes easy, what it makes hard, and the cost we accepted knowingly. Name the thing a future reader will be tempted to "fix" and the reason it is the way it is.

### Confirmation

Optional — name the fitness function only when one exists (a gate check, a contract test, a lint rule). Delete the heading otherwise.

## Pros and Cons of the Options

### Option title

- Good, because …
- Bad, because …

## More Information

Optional — links to related ADRs, upstream issues, or follow-up conditions that would revisit this decision.
