# ADR-0010 — Package-by-component layering, enforced by import-linter

Status: accepted
Date: 2026-09-10

## Context

Two flat-layout reference implementations were measured for structural failure modes: one grew a 7,431-line `switcher.py` plus 2,364- and 1,494-line modules; the other a 4,392-line `config.rs` and 2,635-line `panels.rs`. A sibling project practicing layered package-by-component held ~77 lines/file across 98 files with no god files. The AGENTS.md rules in force already mandate the layered style.

## Decision drivers

- Components are the map: a newcomer navigates by `application/ports/` and `application/use_cases/`, not by memory.
- Layer rules must be mechanically enforced, not review-enforced — import-linter contracts run in the per-commit gate.

## Options considered

| Option | Pro | Con |
| ------ | --- | --- |
| Flat `src/` | Zero ceremony | Measured outcome: god files at scale |
| Deep Clean-Architecture nesting | Maximum separation | Layer dirs with one member add no discoverability |
| Package-by-component, depth ≤ `<component>/<layer>/<module>.py` | Matches measured-good layout; fits AGENTS.md | Requires the structural rules below to stay true |

## Decision

`src/claude_acc_manager/<component>/` with the fixed layer vocabulary: `domain/` (entities, value objects, pure `domain/services/` — zero ports, zero I/O), `application/ports.py` + `application/use_cases/` (one `VerbNoun` class, one `execute()`, orchestrating ports — never another use case), `infrastructure/<mechanism>-<port>.py` adapters (subclass the port explicitly). Cross-component adapters (`cli.py`, future `tui/`) stay top-level and thin, reaching components only through use cases and ports. `__main__.py` is the composition root — the sole importer of concrete adapters.

Import-linter contracts enforce: domain may not import application/infrastructure; application imports ports + domain only; infrastructure imports domain + ports; `accounts` may import `usage` (never the reverse — credential files are an accounts-side concern even when usage consumes them); `cli`/`tui` import use cases and ports only.

Supporting rules (all from the measured convention): a layer dir exists only with ≥2 modules; one concept per file named after the concept; split at concept boundaries or the 500-line ceiling; empty `__init__.py` only; fakes live in `test/support/` as named classes; a **uniform port/use-case surface is preferred over case-by-case minimalism** — a single-implementation port is kept when it keeps every boundary discoverable in one place.

## Consequences

The thing to not "fix": an apparently-justified shortcut like a use case calling another use case, or infrastructure imported in `cli.py`. The contracts are the map's credibility; break one and the doc lies. `accounts` importing `usage` is the one sanctioned asymmetric edge — chosen so credential-file mechanics live with the other account-file mechanics.
