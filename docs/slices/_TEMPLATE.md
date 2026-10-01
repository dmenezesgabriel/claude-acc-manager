# SL-0NN — <capability in the user's words>

Milestone: M<n> · State: open | in-progress | partial | shipped · Depends on: SL-0MM | — · Closes: GAP-NNN | —

> Copy this file to start a milestone. Delete it when the milestone ships.
>
> A PRD exists so the executing agent **never guesses and never assumes**. If a decision can be settled by opening a reference file, this document says which file. Every path is verified on disk in the session that writes the PRD — line ranges rot, so cite paths, and add a line range only where a file is large and the range was checked today.

## Outcome

One sentence: what a user can do afterwards that they cannot do now.

## Exit gate

`uv run pre-commit run --all-files` clean · full `uv run pytest` green · then the manual validation below, run by a human or scripted against the real tool. Measurements go in the closing commit's body.

1. <e.g. register two accounts, exhaust one, run `cam switch --strategy best`>
2. `claude` on the next message signs in as the target account — verify via `cam status`.
3. …

Write this PRD to be grepped: do not hard-wrap paragraphs, keep one fact per table row, write file names in full, and tag every gap it closes with its `GAP-NNN`.

## Who else implements this

**Every reference repo gets a row, including the ones that do not have it** — an absence is evidence too, and a capability present in none is an invention and must be justified.

| Repo | Has it | Entry points | Approach in one line |
| --- | --- | --- | --- |
| claude-swap | FULL/PARTIAL/ABSENT | `src/claude_swap/…` | |
| ai-usagebar | FULL/PARTIAL/ABSENT | `src/…` | |
| claude-code itself (vendor behavior we must interoperate with) | — | e.g. mkdir locks, file pickup semantics | |

**Count:** N of the references implement this. <What that says about whether to build it.>

## Implementation inventory

For **every** repo marked FULL or PARTIAL above, the files an implementer must actually open — not a summary of them. Group by concern. Where two repos disagree, that disagreement **is** the decision the milestone has to make, and it is named.

### <repo name>

| Concern | Files |
| --- | --- |
| Domain logic | |
| Ports / boundaries | |
| Use case / orchestration | |
| Infrastructure adapter | |
| CLI / TUI entry point | |
| Persistence | |
| Error / edge cases | |

## Trade-offs and what we adopt

One row per real decision. "Options seen" must come from the inventory above, not from imagination.

| Axis | Options seen (repo → approach) | Trade-off | Our choice, and why |
| ---- | ------------------------------ | --------- | ------------------- |

## Gap analysis — what we already have vs the references

Read our own code first. A capability that half-exists is worse than one that does not, and this is where that gets caught.

| Concern | Ours today (file) | Best reference (file) | Gap |
| ------- | ----------------- | --------------------- | --- |

State plainly whether ours is: absent · present but unreachable · present and partial · complete.

## Deviations

Anything we will not port as-is, and why. A deviation that outlives the milestone becomes an ADR; the rest is stated in a code comment at the point it applies.

## Open decisions

Anything the references disagree on or none answers. Each needs evidence gathered before it is decided, and an ADR after.

## Surface

| Layer | Files |
| ----- | ----- |
| domain | |
| application (ports / use cases) | |
| infrastructure | |
| cli / tui | |
| tests | |

## Tasks

One TDD unit each, one conventional commit each. Small enough that a unit takes well under an hour; if it does not, decompose further.

- [ ] T1 —
- [ ] T2 —

## Out of scope

What this milestone deliberately does not do, and which milestone or deferred row owns it.
