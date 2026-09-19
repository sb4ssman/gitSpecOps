"""Proof required before a recovery snapshot may be retired.

Being clean, having equal ahead/behind counts, or pushing *some* commit proves nothing about
the work in a snapshot.  This module instead reconstructs the exact Git tree described by a
verified bundle in a disposable index, fetches the repository's upstream, and accepts retirement
only when that freshly checked remote tip has exactly that tree.  It never changes the working
tree, index, branch, or remote.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path
import subprocess
import tempfile

from capture import NO_HELPERS, SAFE_GIT_ENV
from snapshot_store import StoreRefused, verify_bundle


class RetirementRefused(Exception):
    """The snapshot remains: its content was not proved to be remotely reachable."""


def _run(repository: Path, args, *, data=None, env=None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", *NO_HELPERS, *args], cwd=repository, input=data,
                              capture_output=True, timeout=120, check=False,
                              env={**os.environ, **SAFE_GIT_ENV, **(env or {})})
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RetirementRefused("Git could not verify retirement") from exc


def _checked(repository: Path, args, message: str, *, data=None, env=None) -> subprocess.CompletedProcess:
    result = _run(repository, args, data=data, env=env)
    if result.returncode:
        raise RetirementRefused(message)
    return result


def _git_dir_objects(repository: Path) -> Path:
    result = _checked(repository, ["rev-parse", "--git-path", "objects"],
                      "this checkout has no readable Git object store")
    value = result.stdout.decode("utf-8", errors="strict").strip()
    path = Path(value)
    return (repository / path).resolve() if not path.is_absolute() else path.resolve()


def _expected_tree(repository: Path, body: dict) -> str:
    """Build the bundle's exact resulting tree in temporary Git metadata only."""
    base = str(body.get("base_commit") or "")
    _checked(repository, ["cat-file", "-e", f"{base}^{{commit}}"],
             "the snapshot base commit is no longer available locally")
    with tempfile.TemporaryDirectory(prefix="gitspecops-retirement-") as temporary:
        root = Path(temporary)
        objects = root / "objects"
        objects.mkdir()
        environment = {
            "GIT_INDEX_FILE": str(root / "index"),
            # Hashes for carried files go here, not into the user's repository.  Existing base
            # objects are visible read-only through the alternate object directory.
            "GIT_OBJECT_DIRECTORY": str(objects),
            "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(_git_dir_objects(repository)),
        }
        _checked(repository, ["read-tree", base], "could not prepare a proof index", env=environment)
        for patch in (body.get("staged_patch", ""), body.get("unstaged_patch", "")):
            if patch:
                _checked(repository, ["apply", "--cached", "--whitespace=nowarn", "-"],
                         "the saved patch no longer applies to its base", data=patch.encode("utf-8"),
                         env=environment)
        for item in body.get("files", []):
            try:
                content = base64.b64decode(item["content_base64"], validate=True)
                relative = item["path"]
                mode = int(item.get("mode", 0o100644))
            except (KeyError, TypeError, ValueError) as exc:
                raise RetirementRefused("the snapshot's carried file record is malformed") from exc
            if mode not in (0o100644, 0o100755):
                raise RetirementRefused("the snapshot has an unsupported carried-file mode")
            # A carried file is stored byte-for-byte.  Do not let a local autocrlf or
            # attributes rule clean it while constructing the proof tree.
            hashed = _checked(repository, ["hash-object", "-w", "--stdin", "--no-filters"],
                              "could not prepare a carried file for proof", data=content,
                              env=environment).stdout.decode().strip()
            _checked(repository, ["update-index", "--add", "--cacheinfo",
                                  f"{mode:o},{hashed},{relative}"],
                     "could not add a carried file to the proof index", env=environment)
        return _checked(repository, ["write-tree"], "could not write the proof tree",
                        env=environment).stdout.decode().strip()


def prove_retirement(repository, body: dict) -> dict:
    """Return proof details or refuse.  A successful call means `body` may be retired.

    Fetch is intentionally here rather than in the periodic observer: the user asks to retire
    a particular saved copy, and that is the moment when a fresh remote statement is needed.
    """
    try:
        verify_bundle(body)
    except StoreRefused as exc:
        raise RetirementRefused(str(exc)) from exc
    repository = Path(repository).resolve(strict=True)
    _checked(repository, ["rev-parse", "--show-toplevel"], "not a Git checkout")
    _checked(repository, ["fetch", "--no-tags", "origin"],
             "could not freshly fetch origin; the snapshot remains protected")
    upstream = _run(repository, ["rev-parse", "--verify", "@{u}"])
    if upstream.returncode:
        raise RetirementRefused("this checkout has no upstream to prove reachable retirement")
    commit = upstream.stdout.decode().strip()
    _checked(repository, ["merge-base", "--is-ancestor", body["base_commit"], commit],
             "the freshly fetched upstream does not contain the snapshot base")
    expected = _expected_tree(repository, body)
    actual = _checked(repository, ["rev-parse", f"{commit}^{{tree}}"],
                      "could not read the freshly fetched upstream tree").stdout.decode().strip()
    if expected != actual:
        raise RetirementRefused("the freshly fetched upstream does not yet contain exactly the "
                                "saved snapshot content")
    return {"base_commit": body["base_commit"], "remote_commit": commit,
            "tree": actual, "proof": "fresh upstream tree exactly matches the snapshot"}
