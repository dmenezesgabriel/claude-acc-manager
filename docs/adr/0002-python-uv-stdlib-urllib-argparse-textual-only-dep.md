# ADR-0002 — Python + uv; stdlib urllib and argparse; `textual` the only runtime dep

Status: accepted
Date: 2026-09-10

## Context

The tool needs three outbound HTTP calls (usage GET, refresh POST, profile GET), an argparse-class CLI now and a TUI later, on Linux only. The dependency choice sets the supply-chain surface for a program that handles OAuth credentials.

## Decision drivers

- Minimal supply-chain surface: every runtime dep is audit surface on a credential-handling tool.
- The three endpoints need nothing beyond GET/POST + JSON + headers — stdlib `urllib` covers all of it (proven in production: `src/claude_acc_manager/usage/infrastructure/http_transport.py` serving `anthropic_oauth.py`).
- Matches the project's AGENTS.md conventions and keeps the venv reproducible via `uv.lock` pins.

## Options considered

| Option | Pro | Con |
| ------ | --- | --- |
| httpx / requests | Nicer API, connection pooling | +1 permanent dep for three calls that don't need it |
| stdlib `urllib` behind `HttpTransportPort` | Zero deps, injectable seam for hermetic tests | Verbosity lives in our thin wrapper |
| click / typer | Decorators, less boilerplate | +1 dep; argparse suffices for a small verb set |
| stdlib `argparse` | Zero deps, explicit | Manual subcommand wiring |
| rich | Mature TUI primitives | Overlaps textual; two UI deps |
| `textual` (pinned) | Full TUI framework, pilot-testable headless (`TERM=dumb`) | The one runtime dep we carry |

## Decision

Python ≥3.12 managed by uv. Runtime dependency set is exactly `textual`. HTTP is stdlib `urllib` behind `HttpTransportPort`; CLI is stdlib `argparse` in a transport-only `cli.py` (ADR-0013).

## Consequences

Any future need for real HTTP features (HTTP/2, pooling, proxies) must be argued against adding the first networking dep — the thin `HttpTransportPort` seam is where that swap would land without touching use cases. The textual pin is the only runtime package `deptry`/`uv.lock` ever carries; keep it that way.
