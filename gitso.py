"""gitSpecOps common source launcher; Python 3.11+, no installation required.

    python gitso.py commands [--json]        # source-derived catalog; no operations
    python gitso.py docs [COMMAND]          # source documentation to stdout; no files
    python gitso.py update-archive --help   # the direct operation's own parser/help
    python gitso.py scan-tree /path/to/repo --engine none --json
    python gitso.py menu                    # interactive command/argument selection

No arguments shows the menu only in a terminal; otherwise help, without setup or prompts.
Commands forward explicit arguments to existing entry functions, preserving their consent,
settings and output behavior. This is a common front door, not a second operation engine.
Optional integrations stay optional; this launcher never installs aliases or changes profiles.
"""
from __future__ import annotations

import ast
import importlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Command:
    """Static references only. Description/usage comes from the actual script's docstring."""

    name: str
    script: str
    module: str
    handler: str = "main"
    prefix: tuple = ()
    legacy: bool = False

    def documentation(self):
        """Read Python source without importing tools, settings, logging or host clients."""
        return ast.get_docstring(ast.parse((ROOT / self.script).read_text(encoding="utf-8-sig"))) or ""

    def record(self):
        return {"command": self.name, "script": self.script,
                "description": self.documentation().split("\n", 1)[0]}


COMMANDS = (
    Command("discover", "Basic/discover.py", "Basic.discover"),
    Command("duplicate-org", "Special/duplicate_org.py", "Special._org_duplicator.command", "cli_main"),
    Command("update-archive", "Special/update_archive.py", "Special._archive.update_cli"),
    Command("archive-manager", "Special/archive_manager.py", "Special._archive.manager"),
    Command("archive-sync", "Special/archive_sync.py", "Special._archive.sync_cli"),
    Command("inventory-export", "Special/inventory_export.py", "Special.inventory_export"),
    Command("inventory-restore", "Special/inventory_restore.py", "Special.inventory_restore"),
    Command("scan-tree", "Special/security/scan_tree.py", "Special.security._cli", prefix=("tree",)),
    Command("scan-history", "Special/security/scan_history.py", "Special.security._cli", prefix=("history",)),
    Command("review-finding", "Special/security/review_finding.py", "Special.security._review_cli"),
    Command("clean-history", "Special/security/clean_history.py", "Special.security._cleanup_cli"),
    Command("commit", "Special/commit_repo.py", "Special.security._commit.cli"),
    Command("push", "Special/push_repo.py", "Special.security._push_cli"),
    Command("setup", "setup_gitspecops.py", "setup_gitspecops"),
    Command("sync", "git-sync-suggester/sync_suggester.py", "sync_suggester", legacy=True),
    Command("app", "git-sync-suggester/app/fleet_app.py", "fleet_app", legacy=True),
)


def dispatch(command: Command, argv):
    """Invoke one chosen existing CLI adapter; never rewrite scope, argv or authorization."""
    if command.legacy:
        # Existing fleet bootstrap still owns its core/app layout until the reviewed move.
        legacy_root = str(ROOT / "git-sync-suggester")
        if legacy_root not in sys.path:
            sys.path.insert(0, legacy_root)
        importlib.import_module("_paths").bootstrap()
    module = importlib.import_module(command.module)
    result = getattr(module, command.handler)(*command.prefix, list(argv))
    return 0 if result is None else result


def _help():
    print(__doc__)
    for command in COMMANDS:
        print(f"  {command.name:18} {command.record()['description']}")


def menu():
    """Interactive selection only; cancellation/invalid selection never invokes an operation."""
    if not sys.stdin.isatty():
        print("The menu requires a terminal; use commands or an explicit command.", file=sys.stderr)
        return 2
    for number, command in enumerate(COMMANDS, 1):
        print(f"  {number:2}. {command.name}: {command.record()['description']}")
    selected = input("Choose a command number, or leave blank to cancel: ").strip()
    if not selected:
        return 0
    if not selected.isdigit() or not 1 <= int(selected) <= len(COMMANDS):
        print("No command selected.", file=sys.stderr)
        return 2
    command = COMMANDS[int(selected) - 1]
    print(command.documentation())
    print("Enter arguments one per line, without shell quotes. A blank line starts the command; Ctrl+C cancels.")
    arguments = []
    while True:
        argument = input("argument: ")
        if not argument:
            break
        arguments.append(argument)
    return dispatch(command, arguments)


def main(argv=None):
    """Discover/document without imports; dispatch only an explicitly chosen operation."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        if not arguments:
            if sys.stdin.isatty():
                return menu()
            _help()
            return 0
        name, *rest = arguments
        if name in ("-h", "--help", "help"):
            _help()
            return 0
        if name == "commands" and rest in ([], ["--json"]):
            if rest:
                print(json.dumps({"schema_version": 1, "commands": [command.record() for command in COMMANDS]}, indent=2))
            else:
                _help()
            return 0
        if name == "docs" and len(rest) <= 1:
            selected = [command for command in COMMANDS if not rest or command.name == rest[0]]
            if selected:
                for command in selected:
                    print(f"# gitso {command.name}\n\n{command.documentation()}\n")
                return 0
        if name == "menu" and not rest:
            return menu()
        command = next((command for command in COMMANDS if command.name == name), None)
        if command is not None:
            if not rest and not sys.stdin.isatty() and command.name in {
                    "duplicate-org", "archive-manager", "inventory-export", "inventory-restore"}:
                print("This operation needs explicit arguments without a terminal; use --help.", file=sys.stderr)
                return 2
            return dispatch(command, rest)
        print("Unknown command or catalog option; use gitso.py commands.", file=sys.stderr)
        return 2
    except (KeyboardInterrupt, EOFError):
        print("Cancelled.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
