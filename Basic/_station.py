"""The station banner: the header every gitSpecOps terminal screen opens with.

Why:          Sb4ssport's station script design (copied in .agents/knowledge/station-script-design.md)
              gives every screen the same banner, so gitSpecOps looks like the other station tools.
Reads:        nothing; whether stdout is a terminal.
May change:   nothing. It prints.
Results:      the banner on stdout.
Layer:        Basic (presentation plumbing every layer may use; no policy).
Status:       working

The banner: a double bar; `gitSpecOps  /  Page`; on a menu screen the tagline; the publisher
line; the when/computer/user/shell line and any further context lines, printed whole; a double
bar. Bars are 72 wide from column 0 (narrower in a narrower console); text is indented two
spaces. Colours are the standard console names: title Cyan, tagline Gray, publisher and bars
DarkCyan, context DarkGray. Output that is not a terminal gets no colour.
"""
from __future__ import annotations

import getpass
import os
import platform
import shutil
import socket
import sys
from datetime import datetime

PRODUCT = "gitSpecOps"
TAGLINE = "Git Special Operations"
PUBLISHER = "Sb4ssport-Alpha | https://sb4ssport-alpha.github.io"
_TONES = {"accent": "96", "muted": "36", "text": "37", "detail": "90"}


def _colour() -> bool:
    try:
        if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
            return False
    except (AttributeError, ValueError):
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


def _say(text: str, tone: str, colour: bool) -> None:
    print(f"\x1b[{_TONES[tone]}m{text}\x1b[0m" if colour and text else text, flush=True)


def banner(page: str, *context: str, tagline: bool = False) -> None:
    """Print the station banner. `tagline` on menu screens; `context` adds lines after the
    when/computer/user/shell line (what is being changed, where its files are)."""
    colour = _colour()
    columns = shutil.get_terminal_size((80, 24)).columns
    bar = "=" * (min(72, columns - 1) if columns >= 42 else 72)
    when = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print()
    _say(bar, "muted", colour)
    _say(f"  {PRODUCT}  /  {page}", "accent", colour)
    if tagline:
        _say(f"  {TAGLINE}", "text", colour)
    _say(f"  {PUBLISHER}", "muted", colour)
    _say(f"  {when} on {socket.gethostname()}  |  user {getpass.getuser()}  |  Python {platform.python_version()}",
         "detail", colour)
    for text in context:
        if text:
            _say(f"  {text}", "detail", colour)
    _say(bar, "muted", colour)


# --- The rest of a station screen (rows, options, notices, steps), as the design document sets
# them out: text indented two spaces; rows' labels padded to 20; options `[key] Label` with an
# explanation under it; a notice is a title in its status colour, then one plain sentence; steps
# read `[n/total] label  status  seconds  detail`. Every status also has words.
_TONES.update({"strong": "97", "success": "92", "warning": "93", "error": "91"})
STATUS_TONES = {"ok": "success", "changed": "warning", "skipped": "detail", "FAILED": "error"}


def _width() -> int:
    columns = shutil.get_terminal_size((80, 24)).columns
    return min(72, columns - 1) if columns >= 42 else 72


def clean(text) -> str:
    """Anything printed that came from outside the script: no escapes, no control characters."""
    import re
    return re.sub(r"[\x00-\x1f\x7f]", " ", re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", str(text)))


def wrap(text: str, room: int) -> list[str]:
    """Text broken at spaces to fit `room`; a path after a backslash or slash."""
    import re
    rest, lines = clean(text).strip(), []
    while len(rest) > room:
        is_path = re.match(r"(?:[A-Za-z]:\|\\|/|~[\/]|%[A-Z]+%)", rest)
        cut = max(rest.rfind("\\", 0, room), rest.rfind("/", 0, room)) + 1 if is_path else 0
        if cut <= 0:
            cut = rest.rfind(" ", 0, room + 1)
        if cut <= 0:
            cut = max(rest.rfind("\\", 0, room), rest.rfind("/", 0, room)) + 1
        cut = cut if cut > 0 else room
        lines.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    return lines + [rest]


def say(text: str = "", tone: str = "text", end: str = "\n") -> None:
    colour = _colour()
    print(f"\x1b[{_TONES[tone]}m{text}\x1b[0m" if colour and text else text, end=end, flush=True)


def line(text: str = "", tone: str = "text") -> None:
    if not text:
        say()
        return
    for piece in wrap(text, _width() - 2):
        say("  " + piece, tone)


def section(title: str) -> None:
    say()
    line(title, "accent")


def row(label: str, value, tone: str = "text") -> None:
    """A label padded to 20 columns, then the value; continuation lines align under the value."""
    label = clean(label)
    if len(label) >= 20:
        line(label, "muted")
        label = ""
    for number, piece in enumerate(wrap(str(value), max(20, _width() - 22))):
        say(f"  {label if number == 0 else '':<20}", "text", end="")
        say(piece, tone)


def option(key: str, label: str, explanation: str = "") -> None:
    prefix = f"  [{key}] "
    room = max(20, _width() - len(prefix))
    first, *more = wrap(label, room)
    say(prefix, "accent", end="")
    say(first)
    for text in more:
        say(" " * len(prefix) + text)
    for text in (wrap(explanation, room) if explanation else []):
        say(" " * len(prefix) + text, "muted")


def notice(title: str, message: str = "", tone: str = "text") -> None:
    say()
    line(title, tone)
    if message:
        line(message)


def bullet(text: str, tone: str = "text") -> None:
    for number, piece in enumerate(wrap(text, max(20, _width() - 5))):
        say(("   . " if number == 0 else "     ") + piece, tone)


def ask(prompt: str, default: str = "") -> str:
    """One question; Enter takes the default."""
    return input(f"  {prompt} ").strip() or default


def choose(keys: str, default: str) -> str:
    """One of the listed keys (one character each); Enter takes the default; Q exits where 0 does."""
    while True:
        answer = ask(f"Choose [{default.upper()}]:", default).lower()
        if len(answer) == 1 and (answer in keys.lower() or (answer == "q" and "0" in keys)):
            return "0" if answer == "q" else answer
        line("Choose one of the keys shown; nothing has been changed.", "warning")


class Steps:
    """Numbered steps: `[n/total] label` padded to 30, then status, seconds and a short detail."""

    def __init__(self, total: int):
        self.total, self.index, self.results = total, 0, []

    def run(self, label: str, action) -> str:
        """`action()` returns (status, detail); an exception is a FAILED step, never a traceback."""
        import time
        self.index += 1
        say(f"  [{self.index}/{self.total}] {label:<30}", "strong", end="")
        started = time.monotonic()
        try:
            status, detail = action()
        except Exception as exc:  # noqa: BLE001 - a step reports its failure; the run goes on honestly
            status, detail = "FAILED", clean(str(exc)).strip()[:160] or type(exc).__name__
        say(f" {status:<8}", STATUS_TONES[status], end="")
        say(f"{time.monotonic() - started:5.1f}s  {clean(detail)}", "detail")
        self.results.append((label, status, detail))
        return status
