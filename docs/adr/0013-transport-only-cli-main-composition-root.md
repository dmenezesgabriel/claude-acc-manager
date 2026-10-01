# ADR-0013 — `cli.py` is transport-only; `__main__.py` is the composition root; split at 500 lines

Status: accepted
Date: 2026-09-10

## Context

The CLI must be fully drivable in tests with in-memory use cases — no filesystem, no network, no `Path.home()`. It must also be the place real adapters get wired. Those two needs pull in opposite directions unless the transport (argparse + printing) is separated from composition (concrete adapters + ambient env).

This split was also motivated by a real defect: after an earlier split, the `[project.scripts]` entry point still named `cli:main`; the composition-root move fixed the wiring for good.

## Decision drivers

- `cli.run` tests must be hermetic — they inject `UseCases` built on fakes.
- Exactly one module may know the concrete adapter set; otherwise wiring knowledge scatters.

## Options considered

| Option | Pro | Con |
| ------ | --- | --- |
| cli.py both parses and wires | Fewer modules | Ambient env/Path.home() inside cli breaks hermetic tests; adapter imports leak into the transport |
| `cli.py` transport-only + `__main__.py` composition root | cli testable with fakes; single wiring site; import-linter enforces it | `__main__`'s one ambient read (`os.environ`, `Path.home()`) is out of the coverage/mutation floor — justified in-band; `build_use_cases` itself is covered via `test/unit/test_main.py` |

## Decision

`cli.py` holds argparse dispatch and plain-text printing only; it receives a `UseCases` bundle. `__main__.py` imports every concrete adapter and builds the bundle from `os.environ` + `Path.home()`. `cli.py` stays a single file until it crosses the 500-line ceiling, then splits into a package at concept boundaries (the measured convention, not a speculative split).

## Consequences

New commands add a parser + a `_cmd_*` handler in `cli.py` and wire their use case in `__main__.build_use_cases` — nowhere else. The `--json` contract and the root guard (M7) belong to the transport layer, not the use cases.
