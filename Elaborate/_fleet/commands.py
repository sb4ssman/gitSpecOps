"""Route a public Elaborate command to its subcommand in the fleet or status CLI.

Why:          each public file in Elaborate/ names one job, while the two CLIs underneath
              (`cli.py` for the fleet app, `sync_cli.py` for status publishing) keep their
              shared options and lifecycle. Global options must precede the subcommand there,
              so this moves them in front of the injected name.
Reads:        the argument list only.
May change:   nothing itself; the routed subcommand declares its own effect.
Results:      the routed subcommand's exit code.
Layer:        Elaborate: machines or time.
Status:       working
"""
from __future__ import annotations

import sys

GLOBAL_OPTIONS = ("--config-dir", "--settings-home")


def split_globals(argv) -> tuple[list[str], list[str]]:
    """Pull `--config-dir X` / `--settings-home X` (either spelling) out of an argument list."""
    argv = list(argv)
    found, rest, index = [], [], 0
    while index < len(argv):
        token = argv[index]
        if token in GLOBAL_OPTIONS and index + 1 < len(argv):
            found += argv[index:index + 2]
            index += 2
            continue
        if token.startswith(tuple(option + "=" for option in GLOBAL_OPTIONS)):
            found.append(token)
        else:
            rest.append(token)
        index += 1
    return found, rest


def dispatch(main, argv, allowed: tuple[str, ...], default: str, **kwargs) -> int:
    """Run `main` with the chosen subcommand: the first argument if it is one of `allowed`."""
    found, rest = split_globals(sys.argv[1:] if argv is None else argv)
    if rest and rest[0] in allowed:
        name, rest = rest[0], rest[1:]
    else:
        name = default
        if len(allowed) > 1 and rest[:1] in (["-h"], ["--help"]):
            print(f"subcommands: {', '.join(allowed)} (default: {default})\n")
    return main([*found, name, *rest], **kwargs)


def fleet(argv, allowed, default=None, **kwargs) -> int:
    from Elaborate._fleet.cli import main

    return dispatch(main, argv, tuple(allowed), default or allowed[0], **kwargs)


def status(argv, allowed, default=None) -> int:
    from Elaborate._fleet.sync_cli import main

    return dispatch(main, argv, tuple(allowed), default or allowed[0])


def placeholder(name: str, missing: str) -> int:
    print(f"{name} is not built yet: {missing}", file=sys.stderr)
    return 2
