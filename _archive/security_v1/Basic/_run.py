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

`stream()` is the third face, for output too large to collect at once (every file version in a
history, through `git cat-file --batch`). The same care applies -- environment, required
timeout, whole-tree kill -- because a reader that bypassed this wrapper once had none of it.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Iterable, Iterator, Sequence

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


def _child_env(argv: list[str], env: dict[str, str] | None) -> dict[str, str]:
    child_env = dict(os.environ)
    child_env.setdefault("PYTHONUTF8", "1")
    child_env.setdefault("PYTHONIOENCODING", "utf-8")
    if _is_git(argv):
        child_env.setdefault("GIT_TERMINAL_PROMPT", "0")
    child_env.update(env or {})
    return child_env


def run(argv: Sequence, *, timeout: float, cwd: Path | str | None = None,
        env: dict[str, str] | None = None, capture: bool = True) -> Result:
    """Run argv (a list, never a shell string). Never raises for an ordinary failure."""
    argv = [str(part) for part in argv]
    try:
        proc = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE if capture else None,
                                stderr=subprocess.PIPE if capture else None, text=True,
                                encoding="utf-8", errors="replace",
                                env=_child_env(argv, env), **_process.spawn_options())
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


class Stream:
    """A running command's binary stdout, read by the caller as it arrives."""

    def __init__(self, proc: subprocess.Popen):
        self.stdout: IO[bytes] = proc.stdout
        self.timed_out = False
        self.stopped = False
        self._proc = proc

    def stop(self) -> None:
        """End the command early: the caller has read all it wants. Not a failure."""
        self.stopped = True
        _process.kill_tree(self._proc)


@contextmanager
def stream(argv: Sequence, *, timeout: float, cwd: Path | str | None = None,
           env: dict[str, str] | None = None,
           feed: Iterable[bytes] | None = None) -> Iterator[Stream]:
    """Run argv and hand its binary stdout to the caller while it runs.

    `feed` is written to stdin from a thread -- written inline, a request/response command
    deadlocks as soon as both pipes fill -- then stdin is closed. The `timeout` is a deadline for
    the whole command: when it passes, the tree is killed, the caller's reads end, and
    `CommandTimeout` is raised on leaving the block. A missing binary, or a nonzero exit after
    the caller read to the end, raises `CommandFailed`; a partial read must never pass for a
    complete one. Leaving the block early (an exception, an abandoned generator) or calling
    `stop()` kills the tree and raises nothing new.
    """
    argv = [str(part) for part in argv]
    try:
        proc = subprocess.Popen(argv, cwd=cwd,
                                stdin=subprocess.PIPE if feed is not None else subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=_child_env(argv, env), **_process.spawn_options())
    except FileNotFoundError:
        raise CommandFailed(f"Command not found: {argv[0]}") from None
    except (PermissionError, NotADirectoryError) as exc:
        raise CommandFailed(f"cannot start {argv[0]}: {exc}") from None
    handle = Stream(proc)
    deadline = time.monotonic() + timeout
    errors: list[bytes] = []

    def expire() -> None:
        handle.timed_out = True
        _process.kill_tree(proc)

    def collect_errors() -> None:
        try:
            errors.append(proc.stderr.read())
        except (OSError, ValueError):
            pass

    def write() -> None:
        try:
            for chunk in feed:
                proc.stdin.write(chunk)
            proc.stdin.close()
        except (OSError, ValueError):
            pass   # the command ended (or was killed) before taking everything

    timer = threading.Timer(timeout, expire)
    timer.daemon = True
    timer.start()
    helpers = [threading.Thread(target=collect_errors, daemon=True)]
    if feed is not None:
        helpers.append(threading.Thread(target=write, daemon=True))
    for helper in helpers:
        helper.start()
    finished = False
    try:
        yield handle
        finished = True
    finally:
        if finished and not handle.stopped:
            try:
                proc.wait(timeout=max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                handle.timed_out = True
        timer.cancel()
        if proc.poll() is None:
            _process.kill_tree(proc)
        for pipe in (proc.stdout, proc.stdin):
            try:
                if pipe:
                    pipe.close()
            except OSError:
                pass
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            pass
        for helper in helpers:
            helper.join(timeout=5)
    if handle.stopped:
        return
    command = " ".join(argv)
    if handle.timed_out:
        raise CommandTimeout(f"Command timed out after {timeout}s (treated as hung): {command}")
    if proc.returncode:
        detail = b"".join(errors).decode("utf-8", errors="replace").strip()
        raise CommandFailed(f"Command failed: {command}\n{detail}")
