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
