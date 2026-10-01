# ADR-0011 — Strict TDD with a per-commit gate: 95% branch coverage + mutmut

Status: accepted
Date: 2026-09-10 (mutation gate promoted from non-goal to per-commit gate, user decision)

## Context

Sessions have no reviewer memory between them; the gate is the only standing check on quality. A coverage floor alone creates pressure toward weak tests — assertions that execute code without pinning behavior. Mutation testing is the standard mitigation: a mutant that survives proves a test executed the line without constraining it.

## Decision drivers

- A commit must be mechanically impossible unless every gate passes — no `--no-verify`, no config-level skips; every exception is in-band and auditable (`# nosec`, `# pragma: no cover`, `# pragma: no mutate`, each with a written justification).
- Gate latency is a real cost: the mutmut pass is re-measured at each milestone; scoping (e.g. `mutmut run "<changed-module>*"`) is revisited only if a full pass exceeds ~2 min — decided by measurement, not assumption.

## Options considered

| Option | Pro | Con |
| ------ | --- | --- |
| Coverage floor alone | Fast | Weak-test pressure (measured industry failure, not hypothetical) |
| Coverage + mutmut run in CI periodically | Cheap per commit | Survivors accumulate between runs and become un-attributable |
| Coverage ≥95% branch + mutmut per commit, zero disqualifying statuses | Every commit is provably constrained | ~15s–2min per commit; mutmut quirks to learn |

## Decision

TDD strictly (red → green → refactor; test + implementation land in one commit). The pre-commit chain runs: hygiene hooks → ruff + ruff-format → pyright strict → deptry → bandit → vulture → xenon → import-linter → `pytest test/unit --cov --cov-branch --cov-fail-under=95` → `mutmut run` failing on any `survived|no tests|suspicious|timeout|segfault|not checked` status → conventional-commit regex on the message.

Tests are hermetic (no real `$HOME`/`$XDG`/network; paths, clocks, transports injected) and use named fakes from `test/support/`. `-m integration` smoke tests hit the real Anthropic API and are opt-in, excluded from the default run and the coverage denominator.

## Consequences

Measured mutmut 3.7.0 facts that shape the codebase — do not "fix" them blindly:

- mutmut **skips decorated classes/functions entirely** → domain logic lives in module-level functions; dataclass shells only wire it in (see `value_objects.py`'s in-band note).
- The incremental test→function map misses newly-created functions ("no tests") until `rm -rf mutants` — required after structural refactors.
- `# pragma: no mutate` marks provably-equivalent mutants (codec aliases, `cast` type arguments, tie-break comparisons); each carries its justification in-band.
- Under heavy CPU load, mutmut can mark `shared/fsio._write_all` mutants `timeout` via dynamic-timeout miscalibration — a flake, not a defect; idle runs are clean.

pytest runs with `--import-mode=importlib`: the symmetric per-component test layout legitimately produces same-named test modules (`test_system_clock.py` under both `accounts/` and `usage/`), which the default import mode cannot collect.
