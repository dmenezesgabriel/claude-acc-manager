# SL-025 — one fold for the reset-epoch scans

Milestone: M24 · State: open · Depends on: SL-024 · Closes: —

> PRD for M24 (AUD-015). Evidence: `maintainer/research/architecture-audit.md` row AUD-015. Delete this file when the milestone ships.

## Outcome

Afterwards, `src/claude_acc_manager/usage/domain/services/poll_policy.py` carries one walk+parse of `relevant_windows` for reset epochs — the three public queries (`limiting_reset_epoch`, `earliest_future_reset_epoch`, `earliest_reset_epoch`) each read as a single `min`/`max` builtin over it, and the triplicated `# pragma: no mutate` tie-handling comment is gone because no hand-rolled comparison survives to mutate.

## Exit gate

`uv run pre-commit run --all-files` clean · full `uv run pytest` green · then the manual validation below. Measurements go in the closing commit's body.

1. `uv run pytest test/unit/usage/domain/services/test_poll_policy.py` green — the three `Test*ResetEpoch` classes already pin every boundary (pct = 100.0, reset == now_s, continue-not-break scans, models forwarding, None snapshot).
2. `uv run mutmut results` shows no `survived`/`no tests` for `poll_policy.py` — the fold's mutants (`>=`→`>`, `>`→`>=`, `is not None`→`is None`) are all killed by the existing boundary cases.
3. `grep -n "pragma: no mutate" src/claude_acc_manager/usage/domain/services/poll_policy.py` — the three tie-handling sites deleted; any pragma still present is newly introduced with its own justification.

## Who else implements this

Internal deduplication, not a port — but both usage-polling references already carry the folded shape for this exact data, which is what we adopt.

| Repo | Has it | Entry points | Approach in one line |
| --- | --- | --- | --- |
| claude-swap | PARTIAL | `src/claude_swap/poll_policy.py` + `src/claude_swap/usage_store.py` | carries both shapes at once: two hand-rolled max/min loops in poll_policy, and `_earliest_reset` already folded to a comprehension + `min()` in usage_store |
| ai-usagebar | PARTIAL | `src/usage.rs` `ResetCredits::next_expiry` | `filter_map(...).min()` — iterator builtins over optional timestamps; no poll cadence, so no nearer analogue |
| toad | ABSENT | — | no usage-polling concept at all |
| claude-code itself | — | not applicable | the vendor side; no reset-epoch arithmetic to interoperate with |

**Count:** 2 references carry this data; both reach for the iterator/min-max fold. Ours triplicates the older hand-rolled shape — folding follows the direction upstream itself took for `_earliest_reset`.

## Implementation inventory

The fold lives entirely in our own file; the reference files below are the evidence for the chosen shape.

### claude-swap

| Concern | Files |
| --- | --- |
| The hand-rolled shape we fold away from | `research_repos/claude-swap/src/claude_swap/poll_policy.py` — `limiting_reset_ts` (~156), `earliest_future_reset_ts` (~171) |
| The folded shape we adopt | `research_repos/claude-swap/src/claude_swap/usage_store.py` — `_earliest_reset` (~475): comprehension + `min()`, `parse_reset_ts` reused |
| Shared parse | `research_repos/claude-swap/src/claude_swap/poll_policy.py` — `parse_reset_ts` (~184) |

### ai-usagebar

| Concern | Files |
| --- | --- |
| The folded shape we adopt | `research_repos/ai-usagebar/src/usage.rs` — `ResetCredits::next_expiry` (~659): `filter_map` over `Option` timestamps + `min()` |

## Trade-offs and what we adopt

| Axis | Options seen (repo → approach) | Trade-off | Our choice, and why |
| ---- | ---------------------------- | --------- | ------------------- |
| Fold shape | claude-swap poll_policy → hand-rolled loop + tie-pragma; claude-swap `_earliest_reset` / ai-usagebar `next_expiry` → comprehension + `min()` | the hand-rolled loop needs a tie-handling pragma per site; the builtin has no comparison operator to mutate | generator + `min`/`max` builtins with `default=None` — the tie-pragma justification dies with the code, and `default=` removes the empty-check ternary upstream needed (`min(resets) if resets else None`) |
| Where the shared walk lives | `poll_policy.py` private helper vs `headroom.py` (where `relevant_windows` lives) | `headroom` is pure pct arithmetic; `parse_reset_epoch` is poll_policy's | `_window_reset_epochs` private generator in `poll_policy.py`, yielding `(pct, reset_epoch)` pairs — only `limiting_reset_epoch` reads pct, and yielding it folds all three scans on one walk |
| `limiting_reset_epoch` predicate | keep `not (pct < 100.0)` semantics vs `pct >= 100.0` | identical on every real input; differ only on NaN pct | `pct >= 100.0` — the docstring's own contract ("≥100%-utilized") and the codebase's existing convention (`auto/domain/services/auto_rank.py:385` tests maxed as `pct >= 100.0`); see Deviations |

## Gap analysis — what we already have vs the references

| Concern | Ours today (file) | Best reference (file) | Gap |
| ------- | ----------------- | --------------------- | --- |
| Reset-epoch fold | `usage/domain/services/poll_policy.py` — three hand-rolled loops, tie-pragma ×3 | `claude-swap/src/claude_swap/usage_store.py` `_earliest_reset`; `ai-usagebar/src/usage.rs` `next_expiry` | present and correct — duplicated shape, not a behavior gap |
| Past-inclusive earliest reset | `earliest_reset_epoch` — public, feeds `cache_trust.trust_ok` + `cli/json_output.py` | `claude-swap` `usage_store._earliest_reset` — same query, private, already folded | complete — only our copy is unfactored |
| Future-only + at-limit scans | `earliest_future_reset_epoch`, `limiting_reset_epoch` | `claude-swap` `poll_policy.py` `earliest_future_reset_ts`, `limiting_reset_ts` — hand-rolled, unfixed upstream | present — we fold where upstream has not (yet) |

## Deviations

- NaN pct: the old `pct < 100.0 → continue` let a NaN pct through (NaN compares false), counting that window's reset as limiting; the folded `pct >= 100.0` drops it. NaN reaches `pct` only if the API emits a non-standard `NaN` literal; the predicate's documented contract is "at or over 100%", and `auto_rank.py:385` already writes the same test as `>=`. Normalizing toward the contract, not a band-aid for it.
- Upstream's `parse_reset_ts` does a manual `Z → +00:00` substitution; ours relies on `fromisoformat`'s native `Z` support (py3.11+ floor). Unchanged — noted only so the fold isn't mistaken for a port.

## Open decisions

None — the fold shape is settled by both references and the predicate question is resolved in Deviations.

## Surface

| Layer | Files |
| ----- | ----- |
| domain | `src/claude_acc_manager/usage/domain/services/poll_policy.py` |
| application (ports / use cases) | — (callers unchanged: `usage/application/use_cases/fetch_account_usage.py`, `auto/domain/services/auto_rank.py`, `cli/json_output.py`) |
| infrastructure | — |
| cli / tui | — |
| tests | `test/unit/usage/domain/services/test_poll_policy.py` — unchanged; the existing `Test*ResetEpoch` classes are the contract |

## Tasks

One conventional commit each. The fold is a single TDD unit: existing tests pin every behavior, so RED is already satisfied by the suite and the refactor keeps it green — mutmut re-audits the deleted pragma sites at the gate.

- [ ] T1 — `refactor(usage): fold the reset-epoch scans onto min/max` — add `_window_reset_epochs`; rewrite `limiting_reset_epoch`/`earliest_future_reset_epoch`/`earliest_reset_epoch` as `max`/`min` builtins with `default=None`; delete the three tie-handling pragma blocks.
- [ ] T2 — `docs(maintainer): M24 shipped — reset-epoch fold landed` — check this PRD's boxes, mark the backlog row `shipped`, delete this file, record exit-gate numbers in the commit body.

## Out of scope

- `plan_after_fetch`'s 51-line docstring-over-logic shape — AUD-015 judged it contract documentation, not duplication.
- `test_poll_policy.py`'s 711 lines (over the 500 ceiling) — owned by M27's test-suite decomposition.
- Any behavioral change to cadence constants, `plan_after_fetch`, or the trust policy.
