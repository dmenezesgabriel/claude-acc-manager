## Docs map

Start at **`docs/backlog.md`** — it routes everywhere else and names the next milestone to execute.

| Kind | Where | Lifetime |
| --- | --- | --- |
| What to build next | `docs/backlog.md` — the milestone ledger | Edited in place, never appended to |
| How to build one milestone | `docs/slices/SL-NNN-*.md` (from `docs/slices/_TEMPLATE.md`) | **Ephemeral** — written at pickup, deleted on ship |
| Porting evidence & parity snapshots (`research_repos/` citations) | `docs/research/` — created only when a milestone needs them | **Ephemeral** — deleted when the consuming milestone ships |
| Why the system is shaped this way | `docs/adr/` (MADR) and `docs/architecture.md` (arc42) | Durable |

Rules this repo is strict about (docs/adr/0001):

- **Durable docs and code comments never cite `research_repos/`** — cite the
  endpoint, an upstream issue, an ADR, or a `src/` path. Build evidence lives
  in `docs/research/` and `docs/slices/` and dies there.
- **`research_repos/` is read-only and untracked** — never install, import,
  link, vendor, or commit it.
- **Gate results go in commit bodies, never in docs.** Corrections are edits;
  git holds history. No dated blocks.

## Code style

- Functions: 4-20 lines. Split if longer.
- Files: under 500 lines. Split by responsibility.
- One thing per function, one responsibility per module (SRP).
- Names: specific and unique. Avoid `data`, `handler`, `Manager`.
  Prefer names that return <5 grep hits in the codebase.
- Types: explicit. No `any`, no `Dict`, no untyped functions.
- Type aliases that narrow a generic to a component-specific concrete type use
  the `Typed` prefix (e.g. `TypedChatGraph`), following Python's `TypedDict`
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
    (`InMemoryArtifactRepository`, `StreamWriterProgressReporter`,
    `SpecStreamDashboardViewBuilder`) — and subclass the port explicitly, so grepping
    the port name lands on its implementation.
  - Writes go through a use case; reads may hit the repository directly from a router.
- Prefer a uniform port / use-case surface over case-by-case minimalism. Keep a
  single-implementation port when it keeps every boundary and operation discoverable in
  one place (`application/ports/`, `application/use_cases/`) — that consistency is the map
  a newcomer navigates by, not ceremony. Don't strip an abstraction just because it has
  one implementation today.
- Data-agnostic core: no dataset identity in `src/`. Table/column names and domain
  values (and prompt examples that name them) are discovered at runtime via
  `SqlEnginePort` — never hardcoded. Sample-dataset identity lives only in
  `scripts/seed_dev_data.py`, `test/`, and `dev_data/`. Use neutral placeholders
  (`events`, `category`, `amount`) in docstrings/examples. This is a review
  convention, not an automated check — pinning it to the volatile sample-dataset
  names (which get replaced over time) proved too brittle to enforce statically.
- tests must follow triple A pattern (Arrange, Act, Assert) and be grouped within their scope.

## Formatting

- Use the language default formatter (`cargo fmt`, `gofmt`, `prettier`,
  `ruff`, `rubocop -A`). Don't discuss style beyond that.

## Logging

- Structured JSON when logging for debugging / observability.
- Plain text only for user-facing CLI output.
