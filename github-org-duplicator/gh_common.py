"""
gh_common
=========

Shared primitives for the GitHub org duplicator: where run files live, the print lock
that keeps parallel output readable, the one subprocess wrapper every other module uses,
and small console helpers. No GitHub knowledge lives here.
"""

import os
import subprocess
import re
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import NoReturn

TOOL_DIR = Path(__file__).resolve().parent
RUNS_DIR = TOOL_DIR / "runs"
PRINT_LOCK = threading.Lock()

# Upper bound on a single git operation. Large clones are legitimately slow, but a clone
# that has made no progress for this long is hung (dead connection, a credential prompt with
# no terminal, a server that stopped responding) and must not block a worker thread forever.
COMMAND_TIMEOUT_SECONDS = 3600


class CommandTimeout(RuntimeError):
    """run_command exceeded its timeout. A retry rarely helps — the caller should give up."""

# Force UTF-8 so the ✓/✗/→ glyphs and non-ASCII repo names survive on Windows consoles.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


def run_command(cmd, check=True, capture=True, timeout=COMMAND_TIMEOUT_SECONDS, env=None):
    """Run a command (argv list, never a shell) and return the CompletedProcess.

    timeout bounds a hung network operation. git subprocesses always get
    GIT_TERMINAL_PROMPT=0 so a missing credential fails fast instead of blocking on an
    interactive prompt (which, under a thread pool, would deadlock the run). Raises
    RuntimeError on a missing binary, a timeout, or (with check) a nonzero exit.
    """
    run_env = os.environ.copy()
    if cmd and os.path.basename(str(cmd[0])).split(".")[0] == "git":
        run_env.setdefault("GIT_TERMINAL_PROMPT", "0")
    if env:
        run_env.update(env)
    try:
        result = subprocess.run(
            cmd,
            capture_output=capture,
            text=True,
            encoding='utf-8',
            errors='replace',  # replace problematic chars rather than crash on decode
            check=False,
            timeout=timeout,
            env=run_env,
        )
    except FileNotFoundError:
        raise RuntimeError(f"Command not found: {cmd[0]}") from None
    except subprocess.TimeoutExpired:
        raise CommandTimeout(
            f"Command timed out after {timeout}s (treated as hung): {' '.join(map(str, cmd))}"
        ) from None
    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(map(str, cmd))}\n{(result.stderr or '').strip()}")
    return result


def log_message(message, log_file):
    """Print to console and append a timestamped line to a log file (thread-safe)."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {message}"
    with PRINT_LOCK:
        print(message)
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry + '\n')


# VS Code (and some shells) type virtual-env activation commands into a terminal when it
# starts. If a prompt is open when that happens, the activation line lands in our input
# instead of the shell. Skip any line that is clearly one of those rather than treating it
# as an answer. Substrings, not just suffixes: the injected line may have a leading `source `,
# `. `, `& `, or a full path.
_ACTIVATION_MARKERS = (
    "/bin/activate",
    r"\scripts\activate",
    "activate.bat",
    "activate.ps1",
    "activate.fish",
    "activate.csh",
    "conda activate",
)

# Optional queue of pre-supplied answers (see --answers / use_scripted_answers). While it is
# non-empty prompt_input() serves from it and echoes each line; once drained it falls back to
# real input() unless strict mode was requested, in which case a missing answer is an error.
_SCRIPTED_ANSWERS: list[str] = []
_SCRIPTED_STRICT = False


def use_scripted_answers(lines, *, strict=False):
    """Pre-load answers for upcoming prompts (one per line; '' accepts that prompt's default).

    strict=True makes a prompt with no remaining scripted answer a hard error instead of
    dropping back to input() — use it when the process has no usable interactive terminal.
    """
    global _SCRIPTED_ANSWERS, _SCRIPTED_STRICT
    _SCRIPTED_ANSWERS = [str(line).rstrip("\r\n") for line in lines]
    _SCRIPTED_STRICT = bool(strict)


def _looks_like_activation(lowered_value):
    return any(marker in lowered_value for marker in _ACTIVATION_MARKERS)


def _no_answer_available(prompt) -> NoReturn:
    """A prompt is waiting but there is no scripted answer and no usable terminal."""
    raise SystemExit(
        f"\nERROR: an answer is needed but none is available:\n  {prompt!r}\n"
        "Run this in a real terminal, or supply the value as a flag / a line in --answers."
    )


def prompt_input(prompt):
    """Read one answer: from the scripted queue if present, else the terminal.

    Lines that look like an injected virtual-env activation command are ignored rather than
    accepted as the answer (see _ACTIVATION_MARKERS).
    """
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


def format_size(kb):
    """Format a size in KB as a human-readable string. Tolerates None / bad input."""
    try:
        kb = int(kb)
    except (TypeError, ValueError):
        return "size unknown"
    if kb < 0:
        return "size unknown"
    if kb < 1024:
        return f"{kb} KB"
    if kb < 1024 * 1024:
        return f"{kb / 1024:.1f} MB"
    return f"{kb / (1024 * 1024):.1f} GB"


def prompt_yes_no(question, default=True):
    """Ask a yes/no question. Empty input takes the default. Returns a bool."""
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


def prompt_clone_format():
    """Prompt until the user explicitly chooses a working or mirror clone."""
    print("Download format:")
    print("  1. Working repositories (regular clone)")
    print("  2. Mirror repositories (--mirror, archival)")
    while True:
        choice = prompt_input("Format (1 or 2): ")
        if choice in ("1", "2"):
            return choice == "2"
        print("Please choose 1 or 2.")


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


def print_download_warnings() -> None:
    """Uniform download limitations, shown before any download-mode confirmation."""
    print()
    print("-" * 60)
    print("DOWNLOAD BEHAVIOR & LIMITATIONS (applies to every repo below)")
    print("-" * 60)
    print("• Arrival layout: <parent>/<namespace>/<repo> — one folder per namespace.")
    print("• Regular clone: working copy of the default branch (others stay remote-tracking).")
    print("• Mirror clone: full archival copy of all refs, no working tree.")
    print("• Already-local repos are skipped; completed repos are skipped on rerun (resume).")
    print("• Private repos appear only if your authenticated account can see them.")
    print("• LFS repos are flagged; regular clones need `git lfs` installed for content.")
    print("• Sizes shown are GitHub's reported size — real disk use can differ (history, LFS).")
    print("• Failures are collected per repo; the run continues; details land in the runs/ logs.")
    print("• Downloads are local-only: nothing is pushed, created, edited, or deleted remotely.")
    print("• Interactive only — nothing here runs scheduled or in the background.")
    print("-" * 60)
    print()
