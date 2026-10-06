---
status: accepted
date: 2026-09-10
---

# ADR-0002 — Python + uv; stdlib urllib and argparse; `textual` the only runtime dep

## Context and Problem Statement

The tool needs three outbound HTTP calls (usage GET, refresh POST, profile GET), an argparse-class CLI now and a TUI later, on Linux only. The dependency choice sets the supply-chain surface for a program that handles OAuth credentials.

## Decision Drivers

- Minimal supply-chain surface: every runtime dep is audit surface on a credential-handling tool.
- The three endpoints need nothing beyond GET/POST + JSON + headers — stdlib `urllib` covers all of it (proven in production: `src/claude_acc_manager/usage/infrastructure/http_transport.py` serving `anthropic_oauth.py`).
- Matches the project's AGENTS.md conventions and keeps the venv reproducible via `uv.lock` pins.

## Considered Options

- httpx / requests
- stdlib `urllib` behind `HttpTransportPort`
- click / typer
- stdlib `argparse`
- rich
- `textual` (pinned)

## Decision Outcome

Chosen option: "stdlib `urllib` + stdlib `argparse` + `textual` (pinned)", because the three endpoints need nothing beyond GET/POST + JSON + headers and the verb set is small — minimal supply chain on a credential-handling tool.

Python ≥3.12 managed by uv. Runtime dependency set is exactly `textual`. HTTP is stdlib `urllib` behind `HttpTransportPort`; CLI is stdlib `argparse` in a transport-only `cli.py` (ADR-0013).

### Consequences

Any future need for real HTTP features (HTTP/2, pooling, proxies) must be argued against adding the first networking dep — the thin `HttpTransportPort` seam is where that swap would land without touching use cases. The textual pin is the only runtime package `deptry`/`uv.lock` ever carries; keep it that way.

## Pros and Cons of the Options

| Option | Pro | Con |
| ------ | --- | --- |
| httpx / requests | Nicer API, connection pooling | +1 permanent dep for three calls that don't need it |
| stdlib `urllib` behind `HttpTransportPort` | Zero deps, injectable seam for hermetic tests | Verbosity lives in our thin wrapper |
| click / typer | Decorators, less boilerplate | +1 dep; argparse suffices for a small verb set |
| stdlib `argparse` | Zero deps, explicit | Manual subcommand wiring |
| rich | Mature TUI primitives | Overlaps textual; two UI deps |
| `textual` (pinned) | Full TUI framework, pilot-testable headless (`TERM=dumb`) | The one runtime dep we carry |

## More Information

- Amended by M13's CLI UX milestone: `rich>=14.2,<16` joined `textual` as a runtime dep for the human-output layer — `cli/human.py` builds on it directly. The supply-chain argument is unchanged (stdlib HTTP/CLI, UI deps only); the "single runtime dep" phrasing above is the decision as originally recorded. The floor is Python ≥3.11 per `pyproject.toml`.
