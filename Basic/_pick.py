"""Ask the person for a file or a folder: a native dialog when one is safe, the terminal otherwise.

For **commands** (`main()`), never for importable functions. A function that a higher layer or a
scheduled run calls takes its paths as arguments; only a command run by a person with no path
given may ask. That is what lets a Special operation be useful standalone *and* be called by
Elaborate code without any chance of a dialog appearing in an unattended run.

`can_ask()` is the gate: True only when a person is plausibly there (a terminal on stdin) or
answers were scripted with `--answers`. When scripted, or when no dialog is possible (no display,
no tkinter, `GITSPECOPS_NO_GUI=1`, an SSH session), the question is asked in the terminal through
`Basic/_confirm.prompt_input`, so every path through here honours `--answers`. Cancelling returns
None; the caller decides what that means (usually a clean stop). Nothing here is ever a "yes".
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from _os.current import process
from Basic._confirm import prompt_input, scripted_answers_active


def can_ask() -> bool:
    """A person (or a script standing in for one) can answer a question right now."""
    return scripted_answers_active() or process.stdin_is_interactive()


def _dialog_possible() -> bool:
    if scripted_answers_active() or os.environ.get("GITSPECOPS_NO_GUI"):
        return False
    if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False
    if os.environ.get("SSH_CONNECTION") and sys.platform != "win32":
        return False
    return True


def _dialog(kind: str, title: str, initial_dir: Path | None, **options) -> Path | None | bool:
    """Run one tkinter dialog. Returns a Path, None when cancelled, or False when none could open."""
    try:
        import tkinter
        from tkinter import filedialog
        root = tkinter.Tk()
    except Exception:  # ImportError, or TclError with no display: fall back to the terminal
        return False
    try:
        root.withdraw()
        root.attributes("-topmost", True)  # a dialog behind the terminal looks like a hang
        common = {"title": title, "parent": root}
        if initial_dir and Path(initial_dir).is_dir():
            common["initialdir"] = str(initial_dir)
        if kind == "open":
            chosen = filedialog.askopenfilename(**common, **options)
        elif kind == "save":
            chosen = filedialog.asksaveasfilename(**common, **options)
        else:
            chosen = filedialog.askdirectory(**common, mustexist=True)
    except Exception:
        return False
    finally:
        try:
            root.destroy()
        except Exception:
            pass
    return Path(chosen) if chosen else None


def _terminal(prompt: str, default: Path | None = None) -> Path | None:
    hint = f" [{default}]" if default else ""
    raw = prompt_input(f"{prompt}{hint} (blank to cancel{' / accept default' if default else ''}): ")
    if not raw:
        return default
    return Path(os.path.expandvars(os.path.expanduser(raw.strip('"'))))


def pick_open_file(title: str, *, initial_dir: Path | None = None,
                   filetypes: list[tuple[str, str]] | None = None) -> Path | None:
    """Choose an existing file. None if cancelled."""
    if _dialog_possible():
        chosen = _dialog("open", title, initial_dir, filetypes=filetypes or [("All files", "*.*")])
        if chosen is not False:
            return chosen
    return _terminal(f"{title}: path to the file")


def pick_save_file(title: str, *, initial_dir: Path | None = None, initial_name: str = "",
                   default_ext: str = "") -> Path | None:
    """Choose where to write a file (it need not exist). None if cancelled; the terminal
    fallback accepts the suggested location on a blank answer."""
    suggested = (Path(initial_dir) / initial_name) if initial_dir and initial_name else None
    if _dialog_possible():
        chosen = _dialog("save", title, initial_dir, initialfile=initial_name, defaultextension=default_ext)
        if chosen is not False:
            return chosen
    return _terminal(f"{title}: path to write", default=suggested)


def pick_directory(title: str, *, initial_dir: Path | None = None) -> Path | None:
    """Choose an existing folder. None if cancelled."""
    if _dialog_possible():
        chosen = _dialog("dir", title, initial_dir)
        if chosen is not False:
            return chosen
    return _terminal(f"{title}: path to the folder")
