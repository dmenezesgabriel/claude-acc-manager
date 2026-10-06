"""The ``cam`` command's argparse dispatch — transport only, no wiring.

Subcommands print plain text for humans; payload-bearing verbs also take
``--json`` and emit the schema-v1 contract: one
``json.dumps`` object on stdout, camelCase keys, handled failures as an
error envelope on stdout. This package reaches the components only through
use cases (ADR-0010); the concrete adapters are wired in ``__main__`` and
passed in as :class:`UseCases`, so tests drive :func:`run` with in-memory
fakes. Split at the 500-line ceiling per ADR-0013.
"""

from claude_acc_manager.cli.context import ProcessContext, UseCases
from claude_acc_manager.cli.dispatch import run

__all__ = ["ProcessContext", "UseCases", "run"]
