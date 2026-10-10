## Docs map

Start at **`maintainer/backlog.md`** — it routes everywhere else and names the next milestone to execute. A fresh agent session bootstraps via the human-triggered **`/next-task`** skill (`.agents/skills/next-task/SKILL.md`), which runs the orient → scope → PRD → TDD → close loop described below.

| Kind | Where | Lifetime |
| --- | --- | --- |
| What to build next | `maintainer/backlog.md` — the milestone ledger | Edited in place, never appended to |
| How to build one milestone | `maintainer/slices/SL-NNN-*.md` (from `maintainer/slices/_TEMPLATE.md`) | **Ephemeral** — written at pickup, deleted on ship |
| Porting evidence & parity snapshots (`research_repos/` citations) | `maintainer/research/` — created only when a milestone needs them | **Ephemeral** — deleted when the consuming milestone ships |
| Why the system is shaped this way | `docs/adr/` (MADR) and `docs/architecture.md` (arc42) | Durable |

Rules this repo is strict about (docs/adr/0001):

- **Durable docs and code comments never cite `research_repos/`** — cite the
  endpoint, an upstream issue, an ADR, or a `src/` path. Build evidence lives
  in `maintainer/research/` and `maintainer/slices/` and dies there.
- **`research_repos/` is read-only and untracked** — never install, import,
  link, vendor, or commit it.
- **Gate results go in commit bodies, never in docs.** Corrections are edits;
  git holds history. No dated blocks.

## Host resources

<!-- host-resources v1: a standard block, kept word-for-word identical wherever it is used. Limits specific to this repository go under "In this repository", below it. -->

This repository can share its host with other work, and hosts differ. Act on what you measure on the host in front of you, never on a core count, memory size or timing remembered from another run or written in a doc.

**Measure before every heavy command**: a test suite, a coverage or mutation run, a build, a browser, an emulator, a container.

```sh
nproc; cut -d' ' -f1-3 /proc/loadavg                # logical cores; 1, 5 and 15 min load
grep -E 'MemAvailable|SwapFree' /proc/meminfo       # memory a new process can still get
grep some /proc/pressure/cpu /proc/pressure/memory  # avg60: % of the last minute tasks stalled
findmnt -no FSTYPE -T "${TMPDIR:-/tmp}"             # tmpfs: the temp dir is RAM
```

These are Linux's commands; on another OS take the same four readings with its own tools.

- **Wait when the host is busy.** A 1 min load above `nproc` means more runnable tasks than cores, so one more job only lengthens every queue. A memory `some avg60` above zero on two readings a minute apart means tasks already stall for memory. Wait and measure again; if it stays that way, report the readings.
- **Fit the job to the memory.** Start a job only when its measured peak fits in `MemAvailable`. `/usr/bin/time -v <command>` prints `Maximum resident set size` for the largest single process of a run; multiply it by the number of workers.
- **Cap parallelism yourself.** A tool's `auto` worker count takes every logical core. Pass an explicit count of at most half of `nproc`: logical cores usually come two to a physical core, and the rest of the host needs the other half.
- **One heavy command at a time.** Queue the next one; never start two together.
- **Bound and contain every heavy command.** When the host has a job runner (`command -v devjob`), run through it: `devjob <command>`. Otherwise run `nice -n 10 timeout <limit> <command>`, so the job yields the CPU and cannot hang forever.
- **Stop what you start, in the step that finishes with it**: dev servers, browsers, emulators, daemons, containers, watchers. Then list what is left (`pgrep -af <name>`) and stop only processes this session started. One whose parent is alive and is not yours belongs to someone else.
- **Keep bulk off a RAM temp dir.** When the temp dir is `tmpfs`, every byte in it is memory until it is deleted. Installs, virtualenvs, downloaded binaries and large logs go to a path `findmnt -T <path>` shows on a disk filesystem, and you delete them when the task ends.
- **Re-run a failure alone before calling it a regression.** A timeout on a loaded host measures the neighbours. Measure again, run the test by itself, then judge.
- **Never relieve pressure by force.** Do not kill a process you did not start, raise a limit or switch off a cap to get a job through. Report the readings and wait.

### In this repository

- Heavy here: `uv run pytest --cov` and `uv run mutmut run`.
- Run mutmut with `--max-children 2`: its parent held 1.3 GB and each child up to 1.6 GB resident (`ps`, 2026-10-10).

## Code style

- Functions: 4-20 lines. Split if longer.
- Files: under 500 lines. Split by responsibility.
- One thing per function, one responsibility per module (SRP).
- Names: specific and unique. Avoid `data`, `handler`, `Manager`.
  Prefer names that return <5 grep hits in the codebase.
- Types: explicit. No `any`, no `Dict`, no untyped functions.
- Type aliases that narrow a generic to a component-specific concrete type use
  the `Typed` prefix (e.g. `TypedAccountRecord`), following Python's `TypedDict`
  convention. If an alias is shared across more than one module inside the same
  component, it lives in `<component>/infrastructure/types.py` and is imported
  from there — never redefined locally.
- No code duplication. Extract shared logic into a function/module.
- Early returns over nested ifs. Max 2 levels of indentation.
- Exception messages must include the offending value and expected shape.

## Comments

- Keep your own comments. Don't strip them on refactor — they carry
  intent and provenance.
- Write WHY, not WHAT. Skip `// increment counter` above `i++`.
- Docstrings on public functions: intent + one usage example, use google conventions.
- Reference issue numbers / commit SHAs when a line exists because
  of a specific bug or upstream constraint.

## Dependencies

- Inject dependencies through constructor/parameter, not global/import.
- Wrap third-party libs behind a thin interface owned by this project.

## Structure

- Prefer small focused modules over god files.
- Use Package by component (src/component/domain/entities, src/component/domain/value_objects, src/component/application/ports, src/component/application/use_cases, src/component/infrastructure)
- One home per kind of logic (the greppable test — no `application/services/`):
  - **Use case** (`application/use_cases/`): orchestrates injected **ports**. One
    `VerbNoun` class, one `execute()`. A use case depends on ports + domain, **never on
    another use case**.
  - **Domain service** (`domain/services/`): **pure** logic over domain types — zero
    ports, zero I/O. If it needs a port, it is a use case, not a domain service.
  - **Adapter** (`infrastructure/<kind>/`): implements a port; frameworks live here.
    Name it `<Mechanism><PortConcept>` — the mechanism names the tech it wraps
    (`FileAccountStore`, `MkdirClaudeLock`,
    `FlockOpsLock`) — and subclass the port explicitly, so grepping
    the port name lands on its implementation.
  - Writes go through a use case; reads may hit the port directly from the command
    layer (`cli/commands.py` calls `use_cases.account_store.get`, e.g.).
- Prefer a uniform port / use-case surface over case-by-case minimalism. Keep a
  single-implementation port when it keeps every boundary and operation discoverable in
  one place (`application/ports/`, `application/use_cases/`) — that consistency is the map
  a newcomer navigates by, not ceremony. Don't strip an abstraction just because it has
  one implementation today.
- tests must follow triple A pattern (Arrange, Act, Assert) and be grouped within their scope.

## Formatting

- Use the language default formatter (`cargo fmt`, `gofmt`, `prettier`,
  `ruff`, `rubocop -A`). Don't discuss style beyond that.

## Logging

- Structured JSON when logging for debugging / observability.
- Plain text only for user-facing CLI output.
