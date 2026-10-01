"""The ``cam`` argument parser — subcommand names, flags, help text."""

import argparse

from claude_acc_manager.cli.commands import (
    cmd_add,
    cmd_disable,
    cmd_enable,
    cmd_list,
    cmd_remove,
    cmd_status,
    cmd_switch,
    cmd_usage,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the ``cam`` argument parser (each subcommand sets a ``handler``)."""
    parser = argparse.ArgumentParser(prog="cam", description="manage Claude Code OAuth accounts")
    parser.set_defaults(json=False)  # pragma: no mutate — jsonless commands still read args.json
    subparsers = parser.add_subparsers()

    add = subparsers.add_parser("add", help="register an account via an isolated claude login")
    add.add_argument("name", help="account name")
    add.set_defaults(handler=cmd_add)

    remove = subparsers.add_parser("remove", help="unregister an account and delete its login dir")
    remove.add_argument("name", help="account name")
    remove.set_defaults(handler=cmd_remove)

    list_parser = subparsers.add_parser("list", help="list registered accounts")
    list_parser.add_argument("--json", action="store_true", help="emit the schema-v1 JSON payload")
    list_parser.set_defaults(handler=cmd_list)

    status_parser = subparsers.add_parser(
        "status", help="show the account the live claude slot uses"
    )
    status_parser.add_argument(
        "--json", action="store_true", help="emit the schema-v1 JSON payload"
    )
    status_parser.set_defaults(handler=cmd_status)

    usage = subparsers.add_parser("usage", help="show one account's quota usage")
    usage.add_argument("name", help="account name")
    usage.add_argument("--json", action="store_true", help="emit the schema-v1 JSON payload")
    usage.set_defaults(handler=cmd_usage)

    switch = subparsers.add_parser("switch", help="move the live claude login to another account")
    switch.add_argument("name", nargs="?", help="account name (omit to rotate)")
    switch.add_argument(
        "--strategy",
        choices=["best", "next-available"],
        help="pick a target from cached usage instead of naming one",
    )
    switch.add_argument(
        "--dry-run",
        action="store_true",
        help="describe the switch without applying it",
    )
    switch.add_argument("--json", action="store_true", help="emit the schema-v1 JSON payload")
    switch.add_argument(
        "--model",
        help="model preference for cam auto — accepted but not persisted yet",
    )
    switch.set_defaults(handler=cmd_switch)

    disable = subparsers.add_parser("disable", help="hold an account out of automatic switching")
    disable.add_argument("name", help="account name")
    disable.set_defaults(handler=cmd_disable)

    enable = subparsers.add_parser(
        "enable", help="return a disabled account to automatic switching"
    )
    enable.add_argument("name", help="account name")
    enable.set_defaults(handler=cmd_enable)
    return parser
