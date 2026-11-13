"""The station look: how every gitSpecOps terminal screen is drawn.

Why:          every Sb4ssport terminal script looks and behaves the same way (Sb4ssport-Authority
              knowledge/launchers.md, "Station script design"; DCG-Taskforce is the reference,
              PowerCycler the first adoption). This is gitSpecOps' one copy of that pattern, so
              setup, the command menu and the tools all draw the same two screens.
Reads:        nothing; the console's width and whether it is a terminal.
May change:   nothing. It prints, and clears the window before a screen for a person at a console.
Results:      text on stdout.
Layer:        Basic (presentation plumbing every layer may use; no policy).
Status:       working

Two kinds of screen. A **menu screen**: `gitSpecOps  /  Page`, the tagline, the publisher line,
a dash rule; then a notice that leads with the answer, rows, sections and `[key] Label` options,
and `Choose [default]:`. A **run screen**: a double bar above and below the title, publisher and
context lines (when, computer, user, Python; then what is being changed), numbered steps
`[n/total] label  status  seconds  detail`, a Summary and one result notice.
Text is indented two spaces; rules and bars are 72 wide from column 0, narrower in a narrower
console. Colours are the standard console names (the terminal's theme decides the shade) and
every status also has words. Anything printed that came from outside is stripped of control
characters. Output that is not a terminal gets no colour and no clearing.
"""
from __future__ import annotations

import getpass
import os
import platform
import re
import shutil
import socket
import sys
import time
from datetime import datetime

PRODUCT = "gitSpecOps"
TAGLINE = "Every repository on every machine: seen, kept current, protected"
#: The shelf's publisher line, as on every other Sb4ssport station script.
PUBLISHER = "Sb4ssport-Alpha | https://sb4ssport-alpha.github.io"
#: Console colour names as ANSI codes: accent Cyan, muted DarkCyan, text Gray, detail DarkGray,
#: strong White, success Green, warning Yellow, error Red.
TONES = {"accent": "96", "muted": "36", "text": "37", "detail": "90", "strong": "97",
         "success": "92", "warning": "93", "error": "91"}
STATUS_TONES = {"ok": "success", "changed": "warning", "skipped": "detail", "FAILED": "error"}


def _colour_enabled() -> bool:
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        return False
    if sys.platform == "win32":
        try:  # turn on ANSI colours in a classic Windows console
            import ctypes
            kernel = ctypes.windll.kernel32
            handle = kernel.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            if kernel.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel.SetConsoleMode(handle, mode.value | 0x0004)
        except (AttributeError, OSError):
            return False
    return True


COLOUR = _colour_enabled()


def width() -> int:
    columns = shutil.get_terminal_size((80, 24)).columns
    return min(72, columns - 1) if columns >= 42 else 72


def clean(text) -> str:
    """Anything printed that came from outside the script: no escapes, no control characters."""
    return re.sub(r"[\x00-\x1f\x7f]", " ", re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", str(text)))


def wrap(text: str, room: int) -> list[str]:
    """Text broken at spaces to fit `room` columns; a path after a `\\` or `/`."""
    rest, lines = clean(text).strip(), []
    while len(rest) > room:
        # A path breaks after a separator, even one with spaces in it; text breaks at spaces.
        path = re.match(r"(?:[A-Za-z]:\\|\\\\|/|~[\\/]|%[A-Z]+%)", rest)
        cut = max(rest.rfind("\\", 0, room), rest.rfind("/", 0, room)) + 1 if path else 0
        if cut <= 0:
            cut = rest.rfind(" ", 0, room + 1)
        if cut <= 0:
            cut = max(rest.rfind("\\", 0, room), rest.rfind("/", 0, room)) + 1
        cut = cut if cut > 0 else room
        lines.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    return lines + [rest]


def say(text: str = "", tone: str = "text", end: str = "\n") -> None:
    print(f"\x1b[{TONES[tone]}m{text}\x1b[0m" if COLOUR and text else text, end=end, flush=True)


def line(text: str = "", tone: str = "text") -> None:
    """Indented text, wrapped to the console."""
    if not text:
        say()
        return
    for piece in wrap(text, width() - 2):
        say("  " + piece, tone)


def clear_screen() -> None:
    """Every screen starts on a clean window, for a person at a real console only."""
    if COLOUR and sys.stdin.isatty():
        print("\x1b[2J\x1b[3J\x1b[H", end="", flush=True)


def menu_header(page: str) -> None:
    """A menu screen's top: title / page, tagline, publisher, then a dash rule."""
    clear_screen()
    say()
    say(f"  {PRODUCT}  /  {page}", "accent")
    say(f"  {TAGLINE}")
    say(f"  {PUBLISHER}", "muted")
    say("-" * width(), "muted")


def run_header(page: str, *context: str) -> None:
    """A run screen's top: double bars around the title, publisher and context lines. Context
    lines are printed whole, never wrapped."""
    bar = "=" * width()
    when = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    clear_screen()
    say()
    say(bar, "muted")
    say(f"  {PRODUCT}  /  {page}", "accent")
    say(f"  {PUBLISHER}", "muted")
    say(f"  {when} on {socket.gethostname()}  |  user {getpass.getuser()}  |  Python {platform.python_version()}",
        "detail")
    for text in context:
        if text:
            say("  " + clean(text), "detail")
    say(bar, "muted")
    say()


def row(label: str, value, tone: str = "text") -> None:
    """A label padded to 20 columns, then the value; continuation lines align under the value."""
    label = clean(label)
    if len(label) >= 20:
        line(label, "muted")
        label = ""
    for number, piece in enumerate(wrap(str(value), max(20, width() - 22))):
        say(f"  {label if number == 0 else '':<20}", "text", end="")
        say(piece, tone)


def bullet(text: str, tone: str = "text") -> None:
    """`   . text`, wrapped so continuation lines start under the text."""
    for number, piece in enumerate(wrap(text, max(20, width() - 5))):
        say(("   . " if number == 0 else "     ") + piece, tone)


def summary(facts) -> None:
    """The run screen's Summary: an accent title, then `   . fact` bullets."""
    facts = [fact for fact in facts if fact]
    if facts:
        section("Summary")
        for fact in facts:
            bullet(fact)


def option(key: str, label: str, explanation: str = "") -> None:
    """`[key] Label`, with an optional one-line explanation indented under it (muted)."""
    prefix = f"  [{key}] "
    room = max(20, width() - len(prefix))
    first, *more = wrap(label, room)
    say(prefix, "accent", end="")
    say(first)
    for text in more:
        say(" " * len(prefix) + text)
    for text in (wrap(explanation, room) if explanation else []):
        say(" " * len(prefix) + text, "muted")


def section(title: str) -> None:
    say()
    line(title, "accent")


def notice(title: str, message: str = "", tone: str = "text") -> None:
    """A title line in its status colour, then one plain sentence."""
    say()
    line(title, tone)
    if message:
        line(message)


def ask(prompt: str, default: str = "") -> str:
    """One question; Enter takes the default. Scripted answers (`--answers`) are honoured."""
    from Basic._confirm import prompt_input, scripted_answers_active
    if scripted_answers_active():
        return prompt_input(f"  {prompt} ") or default
    return input(f"  {prompt} ").strip() or default


def step_line(index: int, total: int, label: str, status: str, seconds: float, detail: str = "") -> None:
    """One finished step in one print: for work that finishes out of order (a thread pool)."""
    say(f"  [{index}/{total}] {clean(label):<30}", "strong", end="")
    say(f" {status:<8}", STATUS_TONES[status], end="")
    say(f"{seconds:5.1f}s  {clean(detail)}", "detail")


def choose(keys: str, default: str) -> str:
    """A choice from the listed keys (one character each); Enter takes the default, Q exits
    where 0 does. Anything else is asked again."""
    while True:
        answer = ask(f"Choose [{default.upper()}]:", default).lower()
        if len(answer) == 1 and (answer in keys.lower() or (answer == "q" and "0" in keys)):
            return "0" if answer == "q" else answer
        line("Choose one of the keys shown; nothing has been changed.", "warning")


def choose_number(count: int, default: str = "0", letters: str = "") -> str:
    """A choice of `1..count` (any number of digits), the given letters, or 0."""
    allowed = {str(n) for n in range(count + 1)} | set(letters.lower())
    while True:
        answer = ask(f"Choose [{default.upper()}]:", default).lower()
        if answer == "q":
            return "0"
        if answer in allowed:
            return answer
        line("Choose one of the keys shown; nothing has been changed.", "warning")


def clean_lines(output: str) -> list[str]:
    return [clean(text).rstrip() for text in str(output).splitlines() if text.strip()]


class Steps:
    """Numbered steps: `[n/total] label` padded to 30, then status, seconds and detail.
    Status words: ok, changed, skipped, FAILED. A failing step shows its last few output lines,
    never a stack trace."""

    def __init__(self, total: int):
        self.total, self.index, self.results = total, 0, []

    def start(self, label: str) -> float:
        self.index += 1
        say(f"  [{self.index}/{self.total}] {label:<30}", "strong", end="")
        return time.monotonic()

    def done(self, label: str, started: float, status: str, detail: str = "", output: str = "") -> str:
        say(f" {status:<8}", STATUS_TONES[status], end="")
        say(f"{time.monotonic() - started:5.1f}s  {clean(detail)}", "detail")
        if status == "FAILED" and output:
            for text in clean_lines(output)[-8:]:
                say(f"        {text}", "detail")
        self.results.append((label, status, detail))
        return status

    def run(self, label: str, action) -> str:
        """`action()` returns (status, detail, output); an exception is a FAILED step."""
        started = self.start(label)
        try:
            status, detail, output = action()
        except Exception as exc:  # noqa: BLE001 - a step reports its failure; the run goes on honestly
            status, detail, output = "FAILED", type(exc).__name__, str(exc)
        return self.done(label, started, status, detail, output)

    @property
    def failed(self) -> list[str]:
        return [label for label, status, _detail in self.results if status == "FAILED"]


def is_console() -> bool:
    """A person at a console: both ends are a terminal. Screens draw only then."""
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False
