"""The approve step: every question a command asks the person running it goes through here.

Mutation in this project is always detect -> plan -> **approve** -> execute -> review, and this
module is the approve step, so it behaves the same everywhere:

- **Scripted answers.** `use_scripted_answers()` pre-loads answers (a `--answers FILE`), one per
  prompt, echoed as they are used. In strict mode a prompt with no answer left is an error, not
  a hang -- for runs with no usable terminal.
- **Terminal noise is not an answer.** VS Code and some shells type a virtual-env activation
  command into a freshly opened terminal. If a prompt is open at that moment, that line lands
  here; it is recognized and skipped instead of being taken as the choice.
- **No answer is a clean stop.** End of input raises `SystemExit` with a message naming the
  prompt, never an `EOFError` traceback -- and never a silent "yes".
- **Typed confirmation for bulk or remote writes.** `confirm_typed("PUBLISH", ...)` accepts only
  the exact word; anything else, including Enter, declines.
"""
from __future__ import annotations

import os
import re
from typing import NoReturn

# Substrings, not just suffixes: the injected line may carry `source `, `. `, `& `, or a path.
_ACTIVATION_MARKERS = (
    "/bin/activate",
    r"\scripts\activate",
    "activate.bat",
    "activate.ps1",
    "activate.fish",
    "activate.csh",
    "conda activate",
)

_SCRIPTED_ANSWERS: list[str] = []
_SCRIPTED_STRICT = False


def use_scripted_answers(lines, *, strict: bool = False) -> None:
    """Pre-load answers for upcoming prompts (one per line; '' accepts that prompt's default).

    strict=True makes a prompt with no remaining scripted answer a hard error instead of
    dropping back to input() -- use it when the process has no usable interactive terminal.
    """
    global _SCRIPTED_ANSWERS, _SCRIPTED_STRICT
    _SCRIPTED_ANSWERS = [str(line).rstrip("\r\n") for line in lines]
    _SCRIPTED_STRICT = bool(strict)


def _looks_like_activation(lowered_value: str) -> bool:
    return any(marker in lowered_value for marker in _ACTIVATION_MARKERS)


def _no_answer_available(prompt: str) -> NoReturn:
    raise SystemExit(
        f"\nERROR: an answer is needed but none is available:\n  {prompt!r}\n"
        "Run this in a real terminal, or supply the value as a flag / a line in --answers."
    )


def prompt_input(prompt: str) -> str:
    """Read one stripped answer: from the scripted queue if present, else the terminal."""
    while True:
        if _SCRIPTED_ANSWERS:
            value = _SCRIPTED_ANSWERS.pop(0).strip()
            print(f"{prompt}{value}")
        elif _SCRIPTED_STRICT:
            _no_answer_available(prompt)
        else:
            try:
                value = input(prompt).strip()
            except EOFError:
                _no_answer_available(prompt)
        if _looks_like_activation(value.lower()):
            print("Ignoring terminal activation command; please enter your choice.")
            continue
        return value


def prompt_yes_no(question: str, default: bool = True) -> bool:
    """Ask a yes/no question. Empty input takes the default; anything else re-asks."""
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        answer = prompt_input(f"{question} {suffix}: ").lower()
        if not answer:
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("Please answer y or n.")


def confirm_typed(word: str, prompt: str) -> bool:
    """True only when the person types exactly `word`. Enter, or anything else, declines."""
    return prompt_input(prompt) == word


def prompt_for_directory(prompt_text, must_exist=False, create_ok=True):
    """Prompt for a directory, re-prompting until a usable one is given.

    must_exist: the path must already be a directory (upload SOURCE).
    create_ok:  offer to create it when missing (download/migrate TARGET).
    Returns the validated path. Never calls sys.exit on bad input — it re-prompts,
    so a typo doesn't drop the user back to the mode menu.
    """
    while True:
        raw = prompt_input(prompt_text)
        if not raw:
            print("Please enter a path.")
            continue
        path = os.path.expanduser(os.path.expandvars(raw))

        if os.path.isdir(path):
            return path
        if os.path.exists(path):
            print(f"ERROR: {path} exists but is not a directory. Try again.")
            continue

        # Path does not exist.
        if must_exist or not create_ok:
            print(f"ERROR: Directory does not exist: {path}. Try again.")
            continue
        if not prompt_yes_no(f"'{path}' does not exist. Create it?", default=True):
            print("Not created. Enter a different path.")
            continue
        try:
            os.makedirs(path, exist_ok=True)
        except OSError as exc:
            print(f"ERROR: Could not create {path}: {exc}. Try again.")
            continue
        print(f"Created: {path}")
        return path


def resolve_directory(raw, *, must_exist=False, create_missing=False):
    """Non-interactive twin of prompt_for_directory. Returns (path, error).

    error is None on success. Used for a directory supplied as a flag: it validates and
    (when create_missing) creates without asking, so a fully specified run never prompts.
    """
    if not raw:
        return None, "no path given"
    path = os.path.expanduser(os.path.expandvars(raw))
    if os.path.isdir(path):
        return path, None
    if os.path.exists(path):
        return None, f"{path} exists but is not a directory"
    if must_exist or not create_missing:
        return None, f"directory does not exist: {path}"
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as exc:
        return None, f"could not create {path}: {exc}"
    return path, None


def parse_selection(raw, items, key=None):
    """Parse the print-style selection grammar against items. Pure; no I/O.

    Grammar (case-insensitive): 'all'/'a'/'*', ranges '2-4', single numbers,
    literal keys (names), exclusions via 'except' (everything after it) or a '!' prefix.
    Empty raw -> all items. A line made ONLY of exclusions ('!2', 'except 2, 3') implies
    'all'. Numbers are 1-based display positions; a reversed range normalizes;
    out-of-range ranges are reported as bad tokens.

    Returns (selected_items_in_display_order, bad_tokens). bad_tokens non-empty means
    the whole line was rejected and the caller should re-prompt.
    """
    if key is None:
        key = lambda item: str(item).lower()  # noqa: E731
    raw = raw.strip().lower()
    if not raw:
        return list(items), []
    tokens = [t for t in re.split(r"[,\s]+", raw) if t]
    include_all = False
    pending_neg = False  # everything after 'except' is excluded
    picked, exclude, bad = [], set(), []
    for token in tokens:
        if token == "except":
            pending_neg = True
            continue
        neg = pending_neg or token.startswith("!")
        name = token[1:] if token.startswith("!") else token
        if not name:
            bad.append(token)
            continue
        if name in ("all", "a", "*"):
            if neg:
                bad.append(token)
            else:
                include_all = True
            continue
        range_match = re.fullmatch(r"(\d+)-(\d+)", name)
        if range_match:
            lo, hi = int(range_match.group(1)), int(range_match.group(2))
            if lo > hi:
                lo, hi = hi, lo
            if lo < 1 or hi > len(items):
                bad.append(f"{token} (valid: 1-{len(items)})")
                continue
            span = [items[i - 1] for i in range(lo, hi + 1)]
            if neg:
                exclude.update(key(item) for item in span)
            else:
                picked.extend(span)
            continue
        if name.isdigit() and 1 <= int(name) <= len(items):
            item = items[int(name) - 1]
        else:
            item = next((it for it in items if key(it) == name), None)
        if item is None:
            bad.append(token)
        elif neg:
            exclude.add(key(item))
        else:
            picked.append(item)
    if bad:
        return None, bad
    # A line made only of exclusions ('!2', 'except 2, 3') implies 'all': exclusions
    # need a set to subtract from, and the only sensible default is the full list.
    if include_all or (exclude and not picked):
        keep = {key(item) for item in items} - exclude
    else:
        keep = {key(item) for item in picked} - exclude
    return [item for item in items if key(item) in keep], []  # display order, deduped
