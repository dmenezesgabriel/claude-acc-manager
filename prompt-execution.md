# Execution session

You are starting a clean session with no memory of earlier ones. The repo's docs and git history are your memory. Follow these steps in order.

## 1. Orient — grep first, read only what you need

- Run `git log --oneline -15` and `git status --short`. Uncommitted or untracked work means an earlier session stopped partway through — understand it before starting anything new.
- Open `docs/backlog.md`. Its "Finding things" table lists the greps. Find the next milestone: `grep -n "open ← next" docs/backlog.md`.
- If that milestone has a PRD, it is `docs/slices/SL-NNN-*.md` — find its first unchecked task with `grep -n "\[ \]" docs/slices/SL-NNN-*.md`. If it has none, you write it first (§3).
- For a decision, grep the ADR id (`grep -rn "ADR-0009" docs/`) and read only that ADR. For capability parity, `grep -n "GAP-" docs/research/parity-matrix.md`.
- Follow `AGENTS.md`. Do the searches yourself; spawn agents only if I ask.

## 2. Scope

- Work the current milestone's next task; a milestone lands as a series of green commits. If a step is too big, split it in the PRD first, then do the first piece.
- Finish what was started. No new milestone while an earlier one is `open` or `partial`.

## 3. If the milestone has no PRD, write it first

Copy `docs/slices/_TEMPLATE.md` to `docs/slices/SL-NNN-<slug>.md`. A PRD exists so the executing session never guesses and never assumes. It is not ready without:

- **Who else implements this** — a row per reference repo (`claude-swap`, `ai-usagebar`, plus claude-code itself where we interoperate with its behavior), including those lacking the feature. A capability present in none is an invention and must be justified.
- **Implementation inventory** — per repo that has it, the actual files to open grouped by concern (domain, ports, use case, adapter, CLI entry, persistence, edge cases). Paths, not summaries. Where two repos disagree, the disagreement is the decision the milestone must make — name it.
- **Gap analysis** — our code against the references, file against file: absent, unreachable, partial, or complete.

Verify every `research_repos/` path with `test -e` in the session that writes the PRD. Symbol greps find candidates; open the files before counting them. Cite `path` (add a `~N` line hint only if checked today).

## 4. Build — strict TDD, evidence over assumption

- **Before writing code, analyze the source and docs of the reference repos** named in the PRD and take the best of them (`research_repos/`, read-only — never install, import, link, vendor, or commit it).
- Test-driven development strictly: RED → GREEN → REFACTOR. Each unit is one conventional commit (`type(scope): imperative` — scope = component or concern).
- Act on measurement and reading, never on assumption. **No workarounds, no band-aids, no over-engineering, no dead code.** Minimum code that solves the problem; refactor carefully when needed.
- A defect you introduce is yours to fix before you stop, whether or not it was planned — with a regression test.
- You may `curl` and web-search to double-check facts when the references and official docs don't settle one.
- Tests are hermetic (injected paths/clocks/transports), Triple-A, named fakes in `test/support/`, tree mirrors `src/`.

## 5. Close the step

- The gate is the commit: `uv run pre-commit run --all-files` (pyright strict, deptry, bandit, vulture, xenon, import-linter, pytest ≥95% branch, mutmut — see [ADR-0011](docs/adr/0011-strict-tdd-per-commit-gate-coverage-and-mutation.md)). No `--no-verify`, ever.
- Gate and milestone-exit measurements go in the **commit body**, never in a doc.
- Update the PRD checkboxes and the backlog row by **editing** — one line per milestone, no dated blocks.
- When a milestone ships: record the exit-gate numbers in the closing commit body, mark the row `shipped`, delete its slice PRD — durable residue goes into an ADR or a code comment first.
- Stop, and report what shipped, what you measured, and what the next task is.

## Reference repositories — `research_repos/`, read-only and untracked

| Repo | Read it for |
| --- | --- |
| `claude-swap` (v0.27.0b1, Python) | switch transaction + rollback, claude-code mkdir locks, autoswitch loop, poll policy, usage store/backoff, identity oracle |
| `ai-usagebar` (v1.14.0, Rust) | `CLAUDE_CONFIG_DIR` account model, `account switch` (dry-run, outgoing capture), flat 429 backoff, usage response parsing |
| `toad` (v0.6.20, Python) | textual-8.x idioms (`getters`, `@work`/`@on`, `data_bind`, `AUTO_FOCUS`), UX affordances (help panel, throbber, terminal title, breakpoints, key-accelerated menus, schema-driven settings screen), `Visual`/`Strip` renderers, rich CLI output |

Architecture exemplar for conventions: `~/Documents/repos/datastudio` (package-by-component, toolchain pins) — structure only, never features.
