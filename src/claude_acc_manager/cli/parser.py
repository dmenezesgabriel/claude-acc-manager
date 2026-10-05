"""The ``cam`` argument parser — subcommand names, flags, help text."""

import argparse

from claude_acc_manager.cli.commands import (
    cmd_add,
    cmd_auto,
    cmd_config_get,
    cmd_config_list,
    cmd_config_path,
    cmd_config_set,
    cmd_config_unset,
    cmd_disable,
    cmd_enable,
    cmd_list,
    cmd_remove,
    cmd_status,
    cmd_switch,
    cmd_tui,
    cmd_usage,
    cmd_watch,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the ``cam`` argument parser (each subcommand sets a ``handler``)."""
    parser = argparse.ArgumentParser(prog="cam", description="manage Claude Code OAuth accounts")
    parser.set_defaults(json=False)  # pragma: no mutate — jsonless commands still read args.json
    parser.add_argument(
        "--version",
        action="store_true",
        help="print the cam version and exit",
    )
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

    auto = subparsers.add_parser(
        "auto",
        help="auto-switch loop (one tick with --once)",
        description=(
            "Runs a foreground polling loop; --once evaluates once and reports "
            "the outcome in the exit code (0 switched, 1 error, 2 no action, "
            "3 blocked). Defaults come from settings.json; flags override them."
        ),
    )
    auto.add_argument(
        "--once",
        action="store_true",
        help="evaluate once, maybe switch, and exit (exit code = outcome)",
    )
    auto.add_argument(
        "--interval",
        dest="interval_seconds",
        type=float,
        metavar="SECONDS",
        help="poll interval in loop mode",
    )
    auto.add_argument(
        "--threshold",
        type=float,
        metavar="PCT",
        help="switch when the active's binding window reaches this utilization",
    )
    auto.add_argument(
        "--cooldown",
        dest="cooldown_seconds",
        type=float,
        metavar="SECONDS",
        help="minimum time between proactive switches",
    )
    auto.add_argument(
        "--strategy",
        choices=["best", "next-available"],
        help="target selection strategy",
    )
    auto.add_argument(
        "--dry-run",
        action="store_true",
        help="report decisions without switching or writing state",
    )
    auto.add_argument("--json", action="store_true", help="emit one JSON event per line")
    auto.set_defaults(handler=cmd_auto)

    tui = subparsers.add_parser("tui", help="interactive quota dashboard")
    tui.set_defaults(handler=cmd_tui)

    watch = subparsers.add_parser("watch", help="interactive live monitor")
    watch.set_defaults(handler=cmd_watch)

    config = subparsers.add_parser("config", help="view or edit persisted settings")
    config.set_defaults(handler=cmd_config_list)
    config_sub = config.add_subparsers()

    config_list = config_sub.add_parser("list", help="show all effective settings")
    config_list.add_argument("--json", action="store_true", help="emit the schema-v1 JSON payload")
    config_list.set_defaults(handler=cmd_config_list)

    config_get = config_sub.add_parser("get", help="print one setting's effective value")
    config_get.add_argument("key", metavar="KEY", help="dotted key, e.g. autoswitch.threshold")
    config_get.add_argument("--json", action="store_true", help="emit the schema-v1 JSON payload")
    config_get.set_defaults(handler=cmd_config_get)

    config_set = config_sub.add_parser("set", help="validate and persist one setting")
    config_set.add_argument("key", metavar="KEY")
    config_set.add_argument("value", metavar="VALUE")
    config_set.set_defaults(handler=cmd_config_set)

    config_unset = config_sub.add_parser("unset", help="revert one setting to its default")
    config_unset.add_argument("key", metavar="KEY")
    config_unset.set_defaults(handler=cmd_config_unset)

    config_path = config_sub.add_parser("path", help="print the settings.json location")
    config_path.set_defaults(handler=cmd_config_path)
    return parser
