"""Every command's two faces, and its one way to approve: the rules all commands follow.

Why:          a person at a terminal and a program (a script, a scheduler, an AI agent) need
              different output from the same command, and every command that changes things
              should ask for approval the same way.
Reads:        whether stdout and stdin are terminals; GITSPECOPS_OUTPUT.
May change:   nothing. It prints and asks.
Results:      one JSON document, or a station screen.
Layer:        Basic (plumbing every layer may use; no policy).
Status:       working

**Output.** With no terminal attached, a command prints exactly one JSON document on stdout:
`{"command": "<name>", "ok": true|false, ...}`. At a terminal it draws a station screen
(`Basic/_station.py`). `--json` asks for JSON at a terminal too. `GITSPECOPS_OUTPUT=json` or
`=screen` overrides the detection (tests use `screen`, to read what a person would see).
A failure is `{"command": ..., "ok": false, "error": "<one plain sentence>"}` and a nonzero exit.

**Approval.** A command that changes things first works out its plan and changes nothing:

- at a terminal it shows the plan and asks `Apply this plan? [y/N]`;
- with no terminal it prints the plan with its `plan_id` and the exact command that applies it;
- `--apply PLAN_ID` carries the plan out only if the plan worked out now has that same id. If
  anything changed in between, nothing is done and the new plan is printed instead (exit 3).

The plan id is a digest of the plan's own content, so the same situation always gives the same
id and any difference gives another.
"""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import sys
from typing import Callable

#: Exit codes every command uses.
OK, FAILED, USAGE, PLAN_CHANGED = 0, 1, 2, 3


def _terminal(stream) -> bool:
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False


def machine(args=None) -> bool:
    """True when this run answers in JSON: `--json`, no terminal, or GITSPECOPS_OUTPUT=json."""
    choice = os.environ.get("GITSPECOPS_OUTPUT", "").strip().lower()
    if getattr(args, "json", False):
        return True
    if choice in ("json", "screen"):
        return choice == "json"
    return not _terminal(sys.stdout)


def interactive(args=None) -> bool:
    """A person can answer a question: a screen run with a terminal on stdin."""
    return not machine(args) and _terminal(sys.stdin)


def parser(command: str, description: str, **options):
    """An argument parser named as typed (`gitso <command>`), with --json."""
    import argparse
    made = argparse.ArgumentParser(prog=f"gitso {command}", description=description, **options)
    add_json(made)
    return made


def add_json(parser, sub: bool = False) -> None:
    """--json. On a subcommand (`sub`), so it may come after the subcommand's own arguments
    without hiding one given before them."""
    import argparse
    parser.add_argument("--json", action="store_true",
                        default=argparse.SUPPRESS if sub else False,
                        help="answer in JSON even at a terminal (without a terminal it always does)")


def add_apply(parser, many: bool = False) -> None:
    if many:
        parser.add_argument("--apply", metavar="PLAN_ID", action="append",
                            help="carry out the plan with this id (repeat for several); "
                                 "without it the command only shows its plans")
    else:
        parser.add_argument("--apply", metavar="PLAN_ID",
                            help="carry out the plan with this id; without it the command only shows its plan")


def document(command: str, ok: bool = True, /, **fields) -> dict:
    """The record every command prints: its name and whether it succeeded come first and win
    over any same-named field of an engine's own record."""
    return {"command": command, "ok": ok,
            **{key: value for key, value in fields.items() if key not in ("command", "ok")}}


def print_json(record: dict) -> None:
    print(json.dumps(record, indent=2, ensure_ascii=False, default=str), flush=True)


def emit(args, record: dict, screen: Callable[[], None] | None = None) -> None:
    """JSON for a program; the screen for a person (or the JSON, when there is no screen)."""
    if machine(args) or screen is None:
        print_json(record)
    else:
        screen()


def fail(args, command: str, message: str, code: int = USAGE, **fields) -> int:
    """One plain sentence, in the run's own form; returns the exit code."""
    if machine(args):
        print_json(document(command, False, error=message, **fields))
    else:
        from Basic._station import notice
        notice("Stopped", message, "error")
    return code


_VOLATILE = ("generated", "plan_id")


def _steady(value):
    """The plan without when it was made or how long it took, which differ on every run."""
    if isinstance(value, dict):
        return {key: _steady(item) for key, item in value.items()
                if key not in _VOLATILE and "elapsed" not in key}
    if isinstance(value, (list, tuple)):
        return [_steady(item) for item in value]
    return value


def plan_id(plan) -> str:
    """Twelve hex characters from the plan's content: same plan, same id. When it was made
    (`generated`) and how long anything took (`*elapsed*`) do not count."""
    text = json.dumps(_steady(plan), sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def command_line(command: str, argv, hidden=()) -> str:
    """`gitso <command> <arguments>` as typed, without any earlier --apply. The values of the
    `hidden` options (a private reason, say) are shown as a placeholder, never echoed."""
    kept, skip = [], False
    for argument in argv:
        if skip:
            skip = False
            continue
        if argument == "--apply":
            skip = True
            continue
        if argument.startswith("--apply="):
            continue
        name = argument.split("=", 1)[0]
        if name in hidden:
            kept.append(f"{name}=<{name.lstrip('-')}>")
            skip = "=" not in argument
            continue
        kept.append(argument)
    return shlex.join(["gitso", *command.split(), *kept])


class Approval:
    """The plan-then-apply decision for one run. `decide()` returns True when the plan may run;
    when it returns False, `code` is the exit code (OK, or PLAN_CHANGED)."""

    def __init__(self, args, command: str, argv):
        self.args, self.command, self.argv = args, command, list(argv)
        self.given = getattr(args, "apply", None)
        self.code, self.identity = OK, None

    def decide(self, plan, show: Callable[[], None], *, nothing_to_do: bool = False,
               question: str = "Apply this plan?") -> bool:
        identity = plan_id(plan)
        self.identity = identity
        if nothing_to_do:
            emit(self.args, document(self.command, plan=plan, plan_id=identity, applied=False,
                                     message="Nothing to do."), show)
            return False
        if self.given is not None:
            if self.given == identity:
                return True
            record = document(self.command, False, plan=plan, plan_id=identity, applied=False,
                              error="The plan changed since that id was given; nothing was done. "
                                    "Review the plan below and apply its new id.",
                              apply=f"{command_line(self.command, self.argv)} --apply {identity}")
            if machine(self.args):
                print_json(record)
            else:
                show()
                from Basic._station import line, notice
                notice("Plan changed", record["error"], "warning")
                line(record["apply"], "detail")
            self.code = PLAN_CHANGED
            return False
        again = f"{command_line(self.command, self.argv)} --apply {identity}"
        if not interactive(self.args):
            emit(self.args, document(self.command, plan=plan, plan_id=identity, applied=False,
                                     apply=again), show)
            return False
        show()
        from Basic._station import ask, line, notice
        answer = ask(f"{question} [y/N]:", "n").lower()
        if answer in ("y", "yes"):
            return True
        notice("Not applied", "Nothing was changed. To apply this plan later without being asked:")
        line(again, "detail")
        return False


def shown(value) -> str:
    """A value as a person reads it: yes/no, a dash for nothing."""
    if value is None or value == "":
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def report(args, command: str, *, ok: bool, page: str, message: str, context=(), rows=(),
           output: str = "", **fields) -> int:
    """The common finish: one record for a program; for a person the banner, rows, the tool's
    own output, then one result notice. Returns OK or FAILED."""
    record = document(command, ok, message=message, **fields)
    if output.strip():
        record["output"] = output.strip()

    def screen():
        from Basic._station import banner, clean, notice, row, say
        banner(page, *context)
        if rows:
            say()
            for label, value in rows:
                row(label, shown(value))
        if output.strip():
            say()
            for text in output.strip().splitlines():
                say("  " + clean(text), "detail")
        notice("Done" if ok else "Failed", message, "success" if ok else "error")

    emit(args, record, screen)
    return OK if ok else FAILED


def apply_line(command: str, argv, identity: str, hidden=()) -> str:
    """The exact command that applies this plan without being asked."""
    return f"{command_line(command, argv, hidden)} --apply {identity}"


def confirm(question: str = "Apply this plan?") -> bool:
    """Ask a person; anything but y or yes declines."""
    from Basic._station import ask
    try:
        return ask(f"{question} [y/N]:", "n").lower() in ("y", "yes")
    except EOFError:
        return False


def not_applied(command: str, argv, identity: str, hidden=()) -> None:
    """After a person declines: nothing changed, and how to apply it later."""
    from Basic._station import line, notice
    notice("Not applied", "Nothing was changed. To apply this plan later without being asked:")
    line(apply_line(command, argv, identity, hidden), "detail")



def run_plan(args, command: str, argv, operation, *, ready, show, record, code,
             identity=lambda result: result.plan_id, question: str = "Apply this plan?",
             hidden=()) -> int:
    """Plan-then-apply for an operation that works out its own plan id.

    `operation(apply, approve)` returns a result; `ready(result)` says a preview can be applied;
    `show(result, banner)` draws it for a person; `record(result)` is its JSON; `code(result)`
    its exit code. --apply ID applies only that plan. Without it the preview is shown; a person
    at a terminal is asked, and yes applies exactly the plan they saw.
    """
    def finish(result, applied, banner=True):
        fields = record(result)
        exit_code = code(result)
        if not applied and ready(result):
            fields["apply"] = apply_line(command, argv, identity(result), hidden)
        emit(args, document(command, exit_code == OK, applied=applied, **fields),
             lambda: show(result, banner))
        return exit_code

    given = getattr(args, "apply", None)
    if given is not None:
        result = operation(True, given)
        current = identity(result)
        if current and current != given:
            # The plan worked out now is a different one: nothing was done, and the record says so.
            fields = record(result)
            fields["apply"] = apply_line(command, argv, current, hidden)
            emit(args, document(command, False, applied=False, **fields), lambda: show(result, True))
            return PLAN_CHANGED
        return finish(result, True)
    preview = operation(False, None)
    if not (ready(preview) and interactive(args)):
        return finish(preview, False)
    show(preview, True)
    if not confirm(question):
        not_applied(command, argv, identity(preview), hidden)
        return OK
    result = operation(True, identity(preview))
    show(result, False)
    return code(result)


class Gate:
    """Approval for an engine that asks once per plan, mid-run: `gate(action, plan) -> bool`.

    A plan whose id was given with --apply goes ahead. Otherwise a person at a terminal sees it
    and is asked; a program's run declines it, and the plan is kept in `offered` with its id, so
    the result can say exactly what to run to apply it. Declining changes nothing.
    """

    def __init__(self, args, command: str, argv, show_plan):
        self.args, self.command, self.argv, self.show_plan = args, command, list(argv), show_plan
        self.given = set(getattr(args, "apply", None) or ())
        self.offered: list[dict] = []
        self.applied: list[str] = []

    def __call__(self, action: str, plan) -> bool:
        identity = plan_id({"action": action, "plan": plan})
        if identity in self.given:
            self.applied.append(identity)
            return True
        if interactive(self.args):
            self.show_plan(action, plan, identity)
            if confirm(f"Apply this {action} plan?"):
                self.applied.append(identity)
                return True
        self.offered.append({"action": action, "plan_id": identity, "plan": plan})
        return False

    def unused(self) -> list[str]:
        """Given ids that matched no plan this run: those plans changed (or never existed)."""
        return sorted(self.given - set(self.applied))

    def apply_line(self) -> str | None:
        if not self.offered:
            return None
        ids = " ".join(f"--apply {item['plan_id']}" for item in self.offered)
        return f"{command_line(self.command, self.argv)} {ids}"


def outline(title: str, plan, identity: str | None = None) -> None:
    """A plan as a person reads it: each list as a count and its first names, each count as is."""
    from Basic._station import row, section

    def name(item):
        if isinstance(item, dict):
            for key in ("name", "folder", "repo", "root", "path", "id"):
                if item.get(key):
                    return str(item[key])
            return ""
        return str(item)

    def walk(value, prefix=""):
        if not isinstance(value, dict):
            return
        for key, item in value.items():
            label = (prefix + key).replace("_", " ")
            if key in _VOLATILE or "elapsed" in key:
                continue
            if isinstance(item, list):
                names = [name(entry) for entry in item if name(entry)]
                shown_names = ", ".join(names[:6]) + (f", and {len(names) - 6} more" if len(names) > 6 else "")
                row(label, f"{len(item)}" + (f": {shown_names}" if shown_names else ""))
            elif isinstance(item, dict):
                walk(item, label + " ")
            elif isinstance(item, (int, float, bool)) or (isinstance(item, str) and len(item) < 60):
                row(label, shown(item))

    section(title + (f"  (plan {identity})" if identity else ""))
    walk(plan)


class Out:
    """For a command whose work prints as it goes: collect what it says and what it found, then
    finish once, as one JSON record or one screen.

    `say()` takes text the way print() does (a `file=` is accepted and ignored: everything is part
    of the one result). `data()` adds structured fields to the record; on a screen they show as
    rows when `rows=True` is passed to `finish()`.
    """

    def __init__(self, args, command: str, page: str, *context: str):
        self.args, self.command, self.page, self.context = args, command, page, context
        self.lines: list[str] = []
        self.fields: dict = {}

    def say(self, *parts, file=None, sep=" ", end="\n", flush=False) -> None:
        text = sep.join(str(part) for part in parts)
        self.lines.extend(text.splitlines() or [""])

    def data(self, **fields) -> None:
        self.fields.update(fields)

    def finish(self, ok: bool = True, code: int | None = None, *, rows: bool = False,
               message: str | None = None) -> int:
        record = document(self.command, ok, **self.fields)
        if message:
            record["message"] = message
        if self.lines:
            record["lines"] = list(self.lines)

        def screen():
            from Basic._station import banner, clean, notice, say
            banner(self.page, *self.context)
            say()
            for text in self.lines:
                say("  " + clean(text))
            if rows:
                outline("Details", self.fields)
            if message:
                notice("Done" if ok else "Needs attention", message, "success" if ok else "warning")

        emit(self.args, record, screen)
        return (OK if ok else FAILED) if code is None else code
