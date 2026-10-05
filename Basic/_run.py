"""The one subprocess wrapper. Every call out to `git` or a host CLI goes through `run()`.

Two wrappers used to exist and had drifted apart: the shared fact reader's never raised and
had no prompt guard, while the org duplicator's forced ``GIT_TERMINAL_PROMPT=0`` and raised on
everything. Both behaviors are legitimate -- a fact reader wants a result it can inspect, a
worker pool wants an exception it can retry -- so they are two thin faces over one careful core:

- **Always a timeout, and a timeout really stops.** ``timeout`` is required. When it expires
  the whole process tree is killed, not just the direct child: on Windows the child is often a
  launcher (venv ``python.exe``, ``cmd\\git.exe``) whose own child would otherwise keep the output
  pipe open and turn the timeout into a hang. See `_os/*/process.py`.
- **Never interactive.** A git child gets ``GIT_TERMINAL_PROMPT=0`` (unless the caller's own
  environment says otherwise), so a missing credential fails in a second instead of waiting on
  an invisible prompt -- which, under a thread pool, deadlocks the run. Auth belongs to the user.
- **Structured results.** Decoding is UTF-8 with replacement, so a stray byte in a repo name
  never crashes a run. A missing binary or a timeout is a result with a flag, not a traceback.
- **UTF-8 both ways.** Output is decoded as UTF-8, so every child is also told to produce it:
  ``PYTHONUTF8=1`` and ``PYTHONIOENCODING=utf-8`` (unless the caller's environment says
  otherwise). Without them a Python child on Windows writes cp1252 to a pipe, which then
  decodes to the wrong characters or dies on a glyph like ``✓``. They are set for every child,
  not only ones named ``python``, because a launcher, a ``.bat`` or ``uv run`` hides the
  interpreter; other programs ignore them.
- **No policy.** Callers own what they run. Mutating callers reach this only after their own
  plan -> confirm step.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Iterable, Sequence

from _os.current import process as _process

DEFAULT_GIT_TIMEOUT_SECONDS = 45
GIT_TIMEOUT_SECONDS = DEFAULT_GIT_TIMEOUT_SECONDS

#: Exit codes for failures that happen before the child runs, chosen to match shell convention.
EXIT_TIMED_OUT = 124
EXIT_CANNOT_START = 126
EXIT_NOT_FOUND = 127


class Result(subprocess.CompletedProcess):
    """A CompletedProcess that also says whether the child never ran or was cut off."""

    def __init__(self, args, returncode, stdout="", stderr="", *, timed_out=False, missing=False):
        super().__init__(args, returncode, stdout, stderr)
        self.timed_out = timed_out
        self.missing = missing


class CommandFailed(RuntimeError):
    """`run_checked` saw a missing binary or a nonzero exit."""


class CommandTimeout(CommandFailed):
    """`run_checked` exceeded its timeout. A retry rarely helps -- the caller should give up."""


def _is_git(argv: Sequence) -> bool:
    return bool(argv) and os.path.basename(str(argv[0])).split(".")[0].lower() == "git"


def run(argv: Sequence, *, timeout: float, cwd: Path | str | None = None,
        env: dict[str, str] | None = None, capture: bool = True) -> Result:
    """Run argv (a list, never a shell string). Never raises for an ordinary failure."""
    argv = [str(part) for part in argv]
    child_env = dict(os.environ)
    child_env.setdefault("PYTHONUTF8", "1")
    child_env.setdefault("PYTHONIOENCODING", "utf-8")
    if _is_git(argv):
        child_env.setdefault("GIT_TERMINAL_PROMPT", "0")
    child_env.update(env or {})
    try:
        proc = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE if capture else None,
                                stderr=subprocess.PIPE if capture else None, text=True,
                                encoding="utf-8", errors="replace", env=child_env,
                                **_process.spawn_options())
    except FileNotFoundError:
        # Also raised for a cwd that does not exist; either way the child never ran.
        return Result(argv, EXIT_NOT_FOUND, "", f"command not found: {argv[0]}", missing=True)
    except (PermissionError, NotADirectoryError) as exc:
        return Result(argv, EXIT_CANNOT_START, "", f"cannot start {argv[0]}: {exc}")
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _process.kill_tree(proc)
        partial, _ = _drain(proc)
        return Result(argv, EXIT_TIMED_OUT, partial, f"timed out after {timeout}s", timed_out=True)
    except BaseException:  # Ctrl+C included: never leave the tree running behind us
        _process.kill_tree(proc)
        _drain(proc)
        raise
    return Result(argv, proc.returncode, stdout or "", stderr or "")


def _drain(proc: subprocess.Popen) -> tuple[str, str]:
    """Collect what a killed process left in its pipes, without ever waiting long."""
    try:
        out, err = proc.communicate(timeout=5)
        return out or "", err or ""
    except (subprocess.TimeoutExpired, ValueError, OSError):
        for pipe in (proc.stdout, proc.stderr):
            try:
                if pipe:
                    pipe.close()
            except OSError:
                pass
        return "", ""


def run_checked(argv: Sequence, *, timeout: float, cwd: Path | str | None = None,
                env: dict[str, str] | None = None, capture: bool = True) -> Result:
    """`run`, raising `CommandTimeout` / `CommandFailed` instead of returning a failure."""
    result = run(argv, timeout=timeout, cwd=cwd, env=env, capture=capture)
    command = " ".join(result.args)
    if result.timed_out:
        raise CommandTimeout(f"Command timed out after {timeout}s (treated as hung): {command}")
    if result.missing:
        raise CommandFailed(f"Command not found: {result.args[0]}")
    if result.returncode != 0:
        raise CommandFailed(f"Command failed: {command}\n{result.stderr.strip()}")
    return result


def set_git_timeout(seconds: int) -> None:
    """Change the default per-command timeout `run_git` uses (the tools' `--git-timeout`)."""
    global GIT_TIMEOUT_SECONDS
    GIT_TIMEOUT_SECONDS = seconds


def run_git(repo_path: Path | str, args: Iterable[str], timeout: float | None = None,
            env: dict[str, str] | None = None) -> Result:
    """`git <args>` in repo_path with the configured default timeout. Never raises."""
    return run(["git", *args], cwd=repo_path, env=env,
               timeout=GIT_TIMEOUT_SECONDS if timeout is None else timeout)
