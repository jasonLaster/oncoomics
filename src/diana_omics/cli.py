from __future__ import annotations

import argparse
from collections.abc import Callable
from importlib import import_module

from .commands.registry import COMMAND_FAMILIES, COMMAND_SPECS
from .workflow_tasks import TASKS, run_task


def _load_commands() -> dict[str, Callable[[], None]]:
    return {
        command_name: getattr(import_module(command_spec.module), command_spec.callable_name)
        for command_name, command_spec in COMMAND_SPECS.items()
    }


def _format_command_families(command_names: set[str]) -> str:
    lines = ["Command families:"]
    grouped_names: set[str] = set()
    for family in COMMAND_FAMILIES:
        available_names = [name for name in family.commands if name in command_names]
        if not available_names:
            continue
        grouped_names.update(available_names)
        lines.append(f"  {family.title}:")
        lines.append(f"    {family.description}")
        lines.append(f"    {', '.join(available_names)}")
    other_names = sorted(command_names - grouped_names)
    if other_names:
        lines.append("  Other:")
        lines.append(f"    {', '.join(other_names)}")
    return "\n".join(lines)


def main() -> None:
    commands = _load_commands()
    command_names = set(commands) | set(TASKS)
    parser = argparse.ArgumentParser(
        description="Run Python Diana omics workflow commands.",
        epilog=_format_command_families(command_names),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        usage="%(prog)s [-h] [command] [args ...]",
    )
    parser.add_argument("command", nargs="?", metavar="command", help="Command to run. See families below.")
    parser.add_argument("args", nargs=argparse.REMAINDER, metavar="args")
    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        return
    if args.command not in command_names:
        parser.error(f"unknown command: {args.command}")
    if args.command in commands:
        if args.args:
            parser.error(f"{args.command} does not accept extra arguments")
        commands[args.command]()
    else:
        run_task(args.command, args.args)


if __name__ == "__main__":
    main()
