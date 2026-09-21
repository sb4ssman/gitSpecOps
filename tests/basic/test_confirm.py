"""The approve step: scripted answers, activation-noise filtering, yes/no, typed confirmation.

Every mutating command asks through `Basic/_confirm.py`, so its failure behavior is the safety
property: running out of answers must stop cleanly, never hang and never mean "yes"; a typed
confirmation must accept only the exact word.
"""
from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from Basic import _confirm as confirm  # noqa: E402

FAILS: list[str] = []


def check(label: str, ok: bool) -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {label}")
    if not ok:
        FAILS.append(label)


def raises_system_exit(func) -> bool:
    try:
        with redirect_stdout(io.StringIO()):
            func()
    except SystemExit:
        return True
    return False


# ---- scripted answers: queue, echo, strict overflow ----
confirm.use_scripted_answers(["4", "all", "", "y"], strict=True)
out = io.StringIO()
with redirect_stdout(out):
    got = [confirm.prompt_input(f"q{i}: ") for i in range(4)]
check("scripted answers served in order", got == ["4", "all", "", "y"])
check("scripted prompt is echoed", "q0: 4" in out.getvalue())
check("strict overflow stops cleanly", raises_system_exit(lambda: confirm.prompt_input("overflow: ")))

# ---- activation-noise filter ----
confirm.use_scripted_answers(
    ["source /home/u/.venv/bin/activate", "  & C:\\proj\\.venv\\Scripts\\Activate.ps1  ", "4"],
    strict=True,
)
with redirect_stdout(io.StringIO()):
    kept = confirm.prompt_input("mode: ")
check("activation lines skipped, real answer kept", kept == "4")

# ---- yes/no: default on Enter, re-ask on garbage ----
confirm.use_scripted_answers(["", ""], strict=True)
with redirect_stdout(io.StringIO()):
    check("Enter takes default=True", confirm.prompt_yes_no("go?", default=True) is True)
    check("Enter takes default=False", confirm.prompt_yes_no("go?", default=False) is False)
confirm.use_scripted_answers(["maybe", "YES"], strict=True)
with redirect_stdout(io.StringIO()):
    check("garbage re-asks, then yes", confirm.prompt_yes_no("go?", default=False) is True)

# ---- typed confirmation: the exact word only ----
for typed, want in (("PUBLISH", True), ("  PUBLISH  ", True), ("publish", False),
                    ("", False), ("y", False)):
    confirm.use_scripted_answers([typed], strict=True)
    with redirect_stdout(io.StringIO()):
        got_typed = confirm.confirm_typed("PUBLISH", "Type PUBLISH: ")
    check(f"confirm_typed({typed!r}) -> {want}", got_typed is want)

# ---- no terminal at all: a clean stop, never an implicit yes ----
confirm.use_scripted_answers([], strict=False)
real_stdin = sys.stdin
sys.stdin = io.StringIO("")
try:
    check("EOF on a yes/no stops cleanly", raises_system_exit(lambda: confirm.prompt_yes_no("go?")))
    check("EOF on a typed confirm stops cleanly",
          raises_system_exit(lambda: confirm.confirm_typed("YES", "Type YES: ")))
finally:
    sys.stdin = real_stdin

if FAILS:
    print(f"\n{len(FAILS)} FAILED")
    raise SystemExit(1)
print("\nALL-CONFIRM-TESTS-PASS")
