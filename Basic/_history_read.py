"""Bounded raw Git reads for exact-history work; no rewrite, checkout or network.

Reader.object returns authenticated raw object bytes, not log-rendered messages. refs reads
all refs and symbolic HEAD without peeling tags or silently discarding unsupported objects.
Callers decide which types/layouts they support. All subprocesses use Basic's shared wrapper.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re

from Basic._run import run_checked, stream

OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
ENV = {"GIT_NO_REPLACE_OBJECTS": "1", "GIT_NO_LAZY_FETCH": "1", "GIT_OPTIONAL_LOCKS": "0"}
LIMIT = 32 * 1024 * 1024


def _environment():
    # cwd must identify the repository. Ambient Git overrides can redirect even a private
    # mirror command to an unrelated repository/object store; refuse them rather than guess.
    keys = ("GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
            "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_SHALLOW_FILE", "GIT_GRAFT_FILE",
            "GIT_REPLACE_REF_BASE", "GIT_CONFIG", "GIT_CONFIG_PARAMETERS")
    if any(os.environ.get(key) for key in keys):
        raise ValueError("custom Git repository/config environments are unsupported")
    # Hosts may inject safe.directory through Git's counted config environment. Preserve
    # that trust metadata, including its values; it cannot redirect the selected repository.
    count = os.environ.get("GIT_CONFIG_COUNT", "0")
    if not count.isascii() or not count.isdigit() or len(count) > 3 or int(count) > 64:
        raise ValueError("unsupported counted Git configuration")
    if any(os.environ.get(f"GIT_CONFIG_KEY_{index}", "").casefold() != "safe.directory" or
           f"GIT_CONFIG_VALUE_{index}" not in os.environ for index in range(int(count))):
        raise ValueError("custom counted Git configuration is unsupported")


def output(repo, args):
    """Bounded, strictly decoded read; failure is never an empty successful result."""
    _environment()
    with stream(["git", "--no-replace-objects", *args], cwd=repo, env=ENV,
                timeout=60) as child:
        data = child.stdout.read(LIMIT + 1)
        if len(data) > LIMIT:
            raise ValueError("Git read exceeds history limits")
    return data.decode("utf-8")


def refs(repo):
    """Return (all resolved refs, attached HEAD, symbolic alias targets); never discard refs."""
    found, symbolic = {}, {}
    for line in output(repo, ["for-each-ref", "--format=%(refname)%00%(objectname)%00%(symref)"]).splitlines():
        parts = line.split("\0")
        if len(parts) != 3 or not parts[0] or not OID.fullmatch(parts[1]) or parts[0] in found:
            raise ValueError("unsupported or ambiguous ref")
        found[parts[0]] = parts[1]
        if parts[2]:
            symbolic[parts[0]] = parts[2]
    head = output(repo, ["symbolic-ref", "-q", "HEAD"]).strip()
    if head not in found:
        raise ValueError("an attached populated HEAD is required")
    return found, head, symbolic


def complete(repo):
    """Refuse shallow, promisor, grafted and alternate-object repositories before reads."""
    if output(repo, ["rev-parse", "--is-shallow-repository"]).strip() != "false":
        raise ValueError("shallow history is unsupported")
    configured = output(repo, ["config", "--local", "--list"])
    if any(line.partition("=")[0].lower() == "extensions.partialclone" or
           re.fullmatch(r"remote\..*\.promisor", line.partition("=")[0], re.I)
           for line in configured.splitlines()):
        raise ValueError("promisor history is unsupported")
    for name in ("info/grafts", "objects/info/alternates", "objects/info/http-alternates"):
        path = Path(output(repo, ["rev-parse", "--git-path", name]).strip())
        path = path if path.is_absolute() else Path(repo) / path
        if path.exists() or path.is_symlink():
            raise ValueError("grafts and alternate object stores are unsupported")


def integrity(repo):
    """Read-only Git object/connectivity validation. Does not certify privacy or publish."""
    _environment()
    run_checked(["git", "--no-replace-objects", "fsck", "--full", "--strict", "--no-reflogs"],
                cwd=repo, env=ENV, timeout=180)


class Reader:
    """Private bounded cache; validates object length, type and content-address hash."""
    def __init__(self, repo, *, byte_limit=128 * 1024 * 1024, object_limit=10000):
        self.repo, self.byte_limit, self.object_limit = Path(repo), byte_limit, object_limit
        self._cache, self._size = {}, 0

    def __repr__(self):
        return f"Reader(objects={len(self._cache)}, bytes={self._size})"

    def object(self, object_id):
        _environment()
        if not isinstance(object_id, str) or not OID.fullmatch(object_id):
            raise ValueError("a literal object id is required")
        if object_id in self._cache:
            return self._cache[object_id]
        if len(self._cache) >= self.object_limit:
            raise ValueError("history object budget exceeded")
        with stream(["git", "--no-replace-objects", "cat-file", "--batch"], cwd=self.repo,
                    env=ENV, timeout=60, feed=[object_id.encode("ascii") + b"\n"]) as child:
            header = child.stdout.readline(256).decode("ascii").strip().split()
            if (len(header) != 3 or header[0] != object_id or header[1] not in ("commit", "tag", "tree", "blob")
                    or not header[2].isdigit()):
                raise ValueError("missing or unsupported Git object")
            size = int(header[2])
            if size > LIMIT or self._size + size > self.byte_limit:
                raise ValueError("history byte budget exceeded")
            data = child.stdout.read(size)
            if len(data) != size or child.stdout.read(1) != b"\n" or child.stdout.read(1):
                raise ValueError("incomplete object stream")
        kind = header[1]
        digest = hashlib.new("sha1" if len(object_id) == 40 else "sha256")
        digest.update(f"{kind} {size}\0".encode("ascii"))
        digest.update(data)
        if digest.hexdigest() != object_id:
            raise ValueError("object content does not match its id")
        self._cache[object_id] = kind, data
        self._size += size
        return kind, data

    def blob(self, object_id):
        kind, data = self.object(object_id)
        if kind != "blob":
            raise ValueError("expected a file object")
        return data
