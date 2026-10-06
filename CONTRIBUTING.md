# Contributing

Thanks for looking at this. This file exists so review spends its time on your idea rather than on the same handful of mechanical things.

## Before you open a PR

Set up and run the gate — the same chain the commit hooks run:

```sh
uv sync
uv run pre-commit install   # once, so commits gate locally
uv run pre-commit run --all-files
```

That chain is: hygiene hooks → ruff lint+format → pyright strict → deptry → bandit → vulture → xenon → import-linter → pytest (≥95% branch coverage) → mutmut. The mutation gate makes commits slow — that is deliberate; see [ADR-0011](docs/adr/0011-strict-tdd-per-commit-gate-coverage-and-mutation.md) for why. A red gate means the commit does not exist yet — `git commit` runs it again, so fix it before pushing rather than after.

## How changes land

- **Strict TDD** — red → green → refactor; test and implementation land in one commit. `docs/architecture.md` §10 describes the loop.
- **Conventional commits** — `type(scope): imperative`, scope = component or concern. The commit-msg hook enforces the type list, and release automation will parse them.
- **One logical change per commit.** Nothing lands red — the gate is in `pre-commit`, not just CI.
- **Hermetic tests** — injected paths/clocks/transports, named fakes in `test/support/`, `test/` mirrors `src/`. Nothing touches a real `$HOME`/`$XDG` or the network; `-m integration` is opt-in.
- **Docs that mention what you changed** — grep `README.md` and `docs/` for whatever you renamed or removed. A doc that still describes the old behavior is worse than none.

## Picking up work

The milestone ledger is `maintainer/backlog.md`; the next milestone is the row marked `open ← next`, and milestone PRDs live in `maintainer/slices/`. For agent-assisted sessions, `/next-task` (`.agents/skills/next-task/SKILL.md`) is the human-triggered bootstrap.

## Reporting bugs

Use the bug-report issue template — it asks for `cam --version`, `claude --version`, and `cam doctor` output. Never paste credential files or tokens into an issue; `cam` never prints them either. Security problems go through [SECURITY.md](SECURITY.md), not the tracker.
