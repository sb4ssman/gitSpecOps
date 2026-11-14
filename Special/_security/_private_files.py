"""Explicit private JSON storage for reports/review records. No fallback or overwrite.

Outside Git, the caller selects storage and owns its privacy. Inside a work tree, a target
must be untracked and positively ignored. Links/reparse points are refused. New files use
owner-only POSIX permissions; Windows privacy follows the user's directory ACLs. These
checks do not provide an OS sandbox or protection against arbitrary concurrent writers.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat

from Basic._objects import git_output
from Basic._run import run_git
from Special._runtime.files import traverses_link


def _unlinked(path):
    if traverses_link(Path(path)):   # the operating system's own links (macOS /var) are fine
        raise ValueError("private storage must not traverse links")


def private_path(destination):
    """Validate lexical ancestry and Git visibility without creating anything."""
    path = Path(destination).expanduser().absolute()
    if ".." in path.parts:
        raise ValueError("private storage paths must not contain parent traversal")
    _unlinked(path)
    for ancestor in path.parents:
        marker = ancestor / ".git"
        if marker.exists() or marker.is_symlink():
            top = Path(git_output(ancestor, ["rev-parse", "--show-toplevel"]).strip()).resolve()
            # Both sides resolved: Git reports the long form of a short name (RUNNER~1 on
            # Windows) and the canonical form of a system link (/private/var on macOS).
            relative = Path(os.path.realpath(path)).relative_to(top).as_posix()
            if git_output(top, ["ls-files", "--cached", "--", relative]).strip():
                raise ValueError("private storage must not be tracked")
            if run_git(top, ["check-ignore", "-q", "--no-index", "--", relative]).returncode != 0:
                raise ValueError("private storage inside Git must be positively ignored")
            break
        if (ancestor / "HEAD").is_file() and (ancestor / "objects").is_dir() and (ancestor / "refs").is_dir():
            raise ValueError("private storage must not be inside a bare repository")
    return path


def write_private_json(destination, payload):
    """Exclusive durable JSON creation; discard only this operation's incomplete file."""
    path = private_path(destination)
    missing, parent = [], path.parent
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    for parent in reversed(missing):
        parent.mkdir(mode=0o700)
    private_path(path)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
    created = os.fstat(descriptor)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, indent=2, ensure_ascii=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            current = path.lstat()
            if (current.st_dev, current.st_ino) == (created.st_dev, created.st_ino):
                path.unlink()
        except OSError:
            pass
        raise
    return path


def read_private_json(source, *, limit=32 * 1024 * 1024):
    """Read bounded unlinked private state; invalid/missing sources never select defaults."""
    path = private_path(source)
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("private storage must be a regular file")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("private storage must be a regular file")
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("private JSON exceeds its size limit")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("private JSON has duplicate keys")
            result[key] = value
        return result
    def nonfinite(_):
        raise ValueError("nonfinite JSON")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=nonfinite)
    except RecursionError:
        raise ValueError("private JSON exceeds supported nesting") from None
