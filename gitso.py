"""gitSpecOps common source launcher; Python 3.11+, no installation required.

    python gitso.py commands [--json]        # source-derived catalog; no operations
    python gitso.py docs [COMMAND]          # source documentation to stdout; no files
    python gitso.py archive                 # a subject's actions (archive add, archive update, ...)
    python gitso.py archive update --help   # the direct operation's own parser/help
    python gitso.py scan /path/to/repo --engine none --json
    python gitso.py menu                    # interactive command/argument selection

No arguments shows the menu only in a terminal; otherwise help, without setup or prompts.
Commands forward explicit arguments to existing entry functions, preserving their consent,
settings and output behavior. This is a common front door, not a second operation engine.
Optional integrations stay optional; this launcher never changes PATH or shell profiles. Only
setup does, when you choose it there (_build/gitso_command.py), and it can remove them again.
"""
from __future__ import annotations

import ast
import importlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Command:
    """Static references only. Description/usage comes from the actual script's docstring.

    `name` is what you type: one word (`scan`) or a subject and its action (`archive add`).
    `prefix` goes to the handler as positional arguments; `argv` is put in front of what you
    typed (an action word the handler parses itself); `program` is what the handler's help calls
    itself when it adds that action word to it (default: `gitso <name>`)."""

    name: str
    script: str
    module: str
    handler: str = "main"
    prefix: tuple = ()
    argv: tuple = ()
    summary: str = ""
    program: str = ""

    def documentation(self):
        """Read Python source without importing tools, settings, logging or host clients."""
        return ast.get_docstring(ast.parse((ROOT / self.script).read_text(encoding="utf-8-sig"))) or ""

    def description(self):
        return self.summary or self.documentation().split("\n", 1)[0]

    def record(self):
        return {"command": self.name, "script": self.script, "description": self.description()}


def _actions(subject, script, module, handler, actions, program=None):
    """One subject's actions handled by one parser: `gitso <subject> <action>`."""
    return tuple(Command(f"{subject} {action}", script, module, handler, argv=(action,), summary=summary,
                         program=program or f"gitso {subject}")
                 for action, summary in actions)


COMMANDS = (
    # Basic: one Git or host operation, named as git names it.
    Command("discover", "Basic/discover.py", "Basic.discover"),
    Command("status", "Basic/status.py", "Basic.status"),
    Command("fetch", "Basic/fetch.py", "Basic.fetch"),
    Command("pull", "Basic/pull.py", "Basic.pull"),
    Command("clone", "Basic/clone.py", "Basic.clone"),
    Command("reset-keep", "Basic/reset_keep.py", "Basic.reset_keep"),
    # Plain, like git's own: exactly the named files; a push that is never forced. No security
    # check; secure-commit and secure-push (Special) are the checked ones.
    Command("commit", "Basic/commit.py", "Basic.commit"),
    Command("push", "Basic/push.py", "Basic.push"),
    # Special: this machine, once.
    *_actions("machine", "Special/machine.py", "Special._sync.commands", "enroll_machine_main", (
        ("show", "This machine's enrollment: its libraries and how the app shows itself."),
        ("add", "Enroll library folders (shows what it will look through, then asks)."),
        ("remove", "Stop watching one library folder; nothing in it is touched."),
        ("find", "Suggest library folders: folder names only, nothing enrolled."),
        ("presentation", "What double-clicking the tray opens, and whether the web view is served."),
    )),
    Command("machine check", "Special/machine_check.py", "Special._sync.commands", "suggest_sync_main"),
    Command("machine catch-up", "Special/machine_catch_up.py", "Special._sync.commands", "catch_up_main"),
    Command("machine audit", "Special/machine_audit.py", "Special._sync.commands", "audit_repos_main"),
    Command("machine materialize", "Special/machine_materialize.py", "Special._sync.commands", "materialize_main"),
    Command("machine buffers", "Special/machine_buffers.py", "Special._sync.commands", "list_live_buffers_main"),
    Command("repo name", "Special/repo_name.py", "Special._sync.commands", "name_repo_main",
            summary="Give a repository a readable name in this machine's catalog."),
    Command("repo list", "Special/repo_name.py", "Special._sync.commands", "name_repo_main", argv=("--list",),
            summary="List this machine's catalog of repositories and their names.", program="gitso repo list"),
    *_actions("archive", "Special/archive.py", "Special._archive.manager", "main", (
        ("add", "Register a folder of clones and write its launcher (shows the plan first)."),
        ("remove", "Forget a registered archive; its folder and launcher stay."),
        ("list", "The registered archives and their modes."),
        ("status", "The registered archives, checked: folders, launchers, last runs."),
        ("refresh", "Refresh one registered archive, or all, each in its saved mode."),
        ("check", "Check one registered archive, or all, without changing anything."),
    )),
    Command("archive update", "Special/archive_update.py", "Special._archive.update_cli"),
    Command("archive sync", "Special/archive_sync.py", "Special._archive.sync_cli"),
    Command("inventory export", "Special/inventory_export.py", "Special.inventory_export"),
    Command("inventory restore", "Special/inventory_restore.py", "Special.inventory_restore"),
    Command("org copy", "Special/org_copy.py", "Special._org_duplicator.command", "cli_main"),
    Command("scan", "Special/scan.py", "Special._security._cli", prefix=("tree",)),
    Command("review", "Special/review.py", "Special._security._review_cli"),
    Command("history scan", "Special/history_scan.py", "Special._security._cli", prefix=("history",)),
    Command("history clean", "Special/history_clean.py", "Special._security._cleanup_cli"),
    *_actions("history", "Special/history_follow.py", "Special.history_follow", "main", (
        ("follow", "Move this machine's clones onto a rewritten history."),
        ("relink", "Update the commit ids a checkout's files quote, after a rewrite."),
    )),
    Command("secure-commit", "Special/secure_commit.py", "Special._security._commit.cli"),
    Command("secure-push", "Special/secure_push.py", "Special._security._push_cli"),
    # Elaborate: other machines, or over time.
    Command("machine safe-to-wipe", "Elaborate/machine_safe_to_wipe.py", "Elaborate.machine_safe_to_wipe",
            program="gitso machine"),
    Command("archive schedule", "Elaborate/archive_schedule.py", "Elaborate.archive_schedule"),
    *_actions("fleet", "Elaborate/fleet.py", "Elaborate.fleet", "main", (
        ("setup", "Join this enrolled machine to a fleet: a key, then how it shares."),
        ("status", "What is set up, and what each next step unlocks."),
        ("transports", "Choose how this machine shares status: a folder, Tailscale, a repository."),
        ("leave", "Stop sharing with the fleet; the machine stays enrolled."),
        ("key", "The fleet key's details; --show prints the key itself."),
        ("baskets", "Which namespaces this machine observes, publishes and captures."),
        ("git-client", "The desktop Git app the map opens repositories in."),
        ("join", "Enroll, join and start in one step, for scripts (shows the plan first)."),
    )),
    Command("fleet doctor", "Elaborate/fleet_doctor.py", "Elaborate.fleet_doctor", program="gitso fleet"),
    Command("fleet preflight", "Elaborate/fleet_preflight.py", "Elaborate.fleet_preflight", program="gitso fleet"),
    Command("fleet publish", "Elaborate/fleet_publish.py", "Elaborate.fleet_publish"),
    Command("fleet suggest", "Elaborate/fleet_suggest.py", "Elaborate.fleet_suggest", program="gitso fleet"),
    Command("fleet converge", "Elaborate/fleet_converge.py", "Elaborate.fleet_converge", program="gitso fleet"),
    *_actions("peer", "Elaborate/peer.py", "Elaborate.peer", "main", (
        ("run", "Run this machine's peer: watch, publish, serve the map."),
        ("rescan", "Ask the running peer for one fresh look through the libraries."),
    )),
    Command("recovery", "Elaborate/recovery.py", "Elaborate.recovery", program="gitso"),
    Command("start-at-sign-in", "Elaborate/start_at_sign_in.py", "Elaborate.start_at_sign_in", program="gitso"),
    # App: presence and presentation.
    Command("tray", "App/tray.py", "App.tray"),
    Command("serve-web", "App/serve_web.py", "App.serve_web"),
    Command("setup", "_build/setup_gitspecops.py", "_build.setup_gitspecops"),
)

#: Subjects: the first word of a two-word command (`archive` for `archive add`).
SUBJECTS = tuple(dict.fromkeys(command.name.split(" ")[0] for command in COMMANDS if " " in command.name))

#: The menu's headings, in the order the commands are listed.
LAYERS = {"Basic": "Basic: one Git or host operation", "Special": "Special: this machine, once",
          "Elaborate": "Elaborate: other machines, or over time", "App": "App: presence and presentation",
          "_build": "Setup"}


def find(arguments):
    """The command these arguments name, and what is left: two words first, then one."""
    if len(arguments) >= 2:
        command = next((c for c in COMMANDS if c.name == f"{arguments[0]} {arguments[1]}"), None)
        if command is not None:
            return command, arguments[2:]
    if arguments:
        command = next((c for c in COMMANDS if c.name == arguments[0]), None)
        if command is not None:
            return command, arguments[1:]
    return None, arguments


def dispatch(command: Command, argv):
    """Invoke one chosen existing CLI adapter; never rewrite scope, argv or authorization."""
    module = importlib.import_module(command.module)
    # Help and errors name the command as typed: `usage: gitso archive add ...`.
    program, sys.argv[0] = sys.argv[0], command.program or f"gitso {command.name}"
    try:
        result = getattr(module, command.handler)(*command.prefix, [*command.argv, *argv])
    finally:
        sys.argv[0] = program
    return 0 if result is None else result


def subject_help(subject: str, as_json: bool = False) -> int:
    """`gitso archive`: the subject's actions, as a screen or (for a program) one record."""
    actions = [command for command in COMMANDS if command.name.startswith(subject + " ")]
    from Basic import _cli
    if as_json or _cli.machine():
        _cli.print_json(_cli.document(subject, actions=[command.record() for command in actions]))
        return 0
    from Basic._station import banner, line, row, say
    banner(subject.capitalize())
    say()
    for command in actions:
        row(command.name.split(" ", 1)[1], command.description())
    say()
    line(f"gitso {subject} <action> --help shows an action's options.", "muted")
    return 0


def _help():
    print(__doc__)
    layer = None
    for command in COMMANDS:
        if command.script.split("/")[0] != layer:
            layer = command.script.split("/")[0]
            print(f"\n{LAYERS.get(layer, layer)}")
        print(f"  {command.name:22} {command.description()}")


def _arguments(text: str) -> list[str]:
    """One line of arguments, split as a shell would. On Windows backslashes stay as typed."""
    import shlex
    if os.name != "nt":
        return shlex.split(text)
    return [part[1:-1] if len(part) > 1 and part[0] == part[-1] and part[0] in "\"'" else part
            for part in shlex.split(text, posix=False)]


def menu(cancel: str = "cancel"):
    """Interactive selection only; cancellation/invalid selection never invokes an operation.
    `cancel` names what a blank answer does (setup says "go back to setup")."""
    if not sys.stdin.isatty():
        print("The menu requires a terminal; use commands or an explicit command.", file=sys.stderr)
        return 2
    from Basic._station import ask, banner, line, option, say, section
    banner("Commands", tagline=True)
    layer = None
    for number, command in enumerate(COMMANDS, 1):
        if command.script.split("/")[0] != layer:
            layer = command.script.split("/")[0]
            section(LAYERS.get(layer, layer))
        option(str(number), command.name, command.description())
    say()
    while True:
        selected = ask(f"Choose a command number, or press Enter to {cancel}:")
        if not selected:
            return 0
        if selected.isdigit() and 1 <= int(selected) <= len(COMMANDS):
            break
        line(f"Choose a number from 1 to {len(COMMANDS)}; nothing has been run.", "warning")
    command = COMMANDS[int(selected) - 1]
    banner(f"Commands  /  {command.name}")
    say()
    for text in command.documentation().splitlines():
        line(text, "muted") if text.strip() else say()
    say()
    line("Type its arguments as you would after the command name, on one line. Commands that "
         "change things show their plan first and ask. Enter alone runs it with none; Ctrl+C cancels.")
    try:
        arguments = _arguments(ask(f"gitso {command.name}"))
    except ValueError:
        line("Those arguments have an unmatched quote; nothing has been run.", "warning")
        return 2
    say()
    return dispatch(command, arguments)


#: Commands that need explicit arguments when nobody is at a terminal to be asked.
NEEDS_ARGUMENTS = {"org copy", "inventory export", "inventory restore"}


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
                print(json.dumps({"command": "commands", "ok": True,
                                  "commands": [command.record() for command in COMMANDS]}, indent=2))
            else:
                _help()
            return 0
        if name == "docs" and len(rest) <= 2:
            wanted = " ".join(rest)
            selected = [command for command in COMMANDS
                        if not rest or command.name == wanted or command.name.startswith(wanted + " ")]
            if selected:
                shown = set()
                for command in selected:
                    if command.script not in shown:
                        shown.add(command.script)
                        print(f"# gitso {command.name}\n\n{command.documentation()}\n")
                return 0
        if name == "menu" and not rest:
            return menu()
        command, remaining = find(arguments)
        if command is not None:
            if not remaining and not sys.stdin.isatty() and command.name in NEEDS_ARGUMENTS:
                print("This operation needs explicit arguments without a terminal; use --help.", file=sys.stderr)
                return 2
            return dispatch(command, remaining)
        if name in SUBJECTS and (not rest or rest[0] in ("-h", "--help", "help", "--json")):
            if name == "archive" and not rest and sys.stdin.isatty() and sys.stdout.isatty():
                from Special._archive.manager import menu_main
                return menu_main([])
            return subject_help(name, as_json=rest == ["--json"])
        if name in SUBJECTS:
            print(f"Unknown action for {name}: {rest[0]}. Its actions: gitso {name} --help", file=sys.stderr)
            return 2
        print("Unknown command; gitso commands lists them.", file=sys.stderr)
        return 2
    except (KeyboardInterrupt, EOFError):
        print("Cancelled.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
