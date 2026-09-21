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
