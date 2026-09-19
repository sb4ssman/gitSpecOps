"""Recovery snapshot preview: what a bundle would do, before anything touches a disk.

A bundle arrives in the synced folder written by *another machine*. Even with a verified
checksum it is untrusted input -- a checksum proves the bytes are what that machine wrote, not
that what it wrote is safe. So before a restore is even offered, preview answers two questions
without extracting or writing anything:

1. **What would this change?** Files touched by the staged patch, by the unstaged patch, and the
   untracked files carried whole, with the base commit a restore must start from.
2. **Can it be restored safely and faithfully?** Every path is checked against traversal,
   absolute and drive paths, `.git`, Windows reserved names and case-insensitive collisions.
   Carried files are checked against their recorded size and digest. A patch that is truncated,
   malformed, holds a binary change without its content, or creates a symbolic link or
   submodule is reported, not guessed at.

Problems are collected rather than raised, so the user sees everything wrong with a bundle at
once. A bundle with any problem is `restorable: False`; restore will refuse it.

This is deliberately in-memory. The design allows preview in a scratch directory, but a preview
that writes nothing cannot be tricked into writing something. Patch parsing itself lives in
`patch_parse.py`, which secret screening shares.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import re

from patch_parse import PatchUnreadable, parse_patch
from shared.git_facts import run_git
from snapshot_store import verify_bundle

COMMIT = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{n}" for n in range(1, 10)),
                    *(f"lpt{n}" for n in range(1, 10))}
WINDOWS_INVALID = set('<>:"|?*')

# Kept for callers written before parsing moved to `patch_parse`.
PreviewRefused = PatchUnreadable


def path_problem(path) -> str:
    """Why a repository-relative path is unsafe to restore on any platform, or `""`.

    Restore may run on Windows even when capture ran on Linux, so a path must be safe on both.
    """
    if not isinstance(path, str) or not path:
        return "empty path"
    if "\0" in path or any(ord(char) < 32 for char in path):
        return "control character in path"
    if "\\" in path:
        return "backslash in path"
    if path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        return "absolute path"
    for part in path.split("/"):
        if part in ("", ".", ".."):
            return "path traversal or empty segment"
        if part.lower() == ".git":
            return "path inside .git"
        if part.endswith((".", " ")):
            return "segment ends with a dot or space"
        if part.split(".")[0].lower() in WINDOWS_RESERVED:
            return "Windows reserved name"
        if WINDOWS_INVALID & set(part):
            return "character not allowed on Windows"
    return ""


def _patch_listing(label: str, text, problems: list) -> list[dict]:
    if not isinstance(text, str):
        problems.append(f"{label} patch is not text")
        return []
    try:
        entries = parse_patch(text)
    except PatchUnreadable as exc:
        problems.append(f"{label} patch: {exc}")
        return []
    listing, seen = [], set()
    for entry in entries:
        if not entry["path"]:
            problems.append(f"{label} patch: a file section names no path")
            continue
        for candidate in {entry["path"], entry["old"]} - {None}:
            reason = path_problem(candidate)
            if reason:
                problems.append(f"{label} patch: {reason}: {candidate!r}")
        if entry["path"].casefold() in seen:
            problems.append(f"{label} patch: {entry['path']!r} appears more than once")
        seen.add(entry["path"].casefold())
        if entry["binary"] and not entry["binary_content"]:
            problems.append(f"{label} patch: binary change to {entry['path']!r} has no content")
        if entry["unsupported"]:
            problems.append(f"{label} patch: {entry['path']!r} is a {entry['unsupported']}, "
                            "which restore does not support")
        item = {"path": entry["path"], "change": entry["change"], "binary": entry["binary"]}
        if entry["change"] in ("renamed", "copied"):
            item["from"] = entry["old"]
        listing.append(item)
    return listing


def preview(body: dict) -> dict:
    """Describe a verified bundle and every reason it cannot be restored. Writes nothing."""
    verify_bundle(body)
    problems: list[str] = []
    if not COMMIT.fullmatch(str(body.get("base_commit", ""))):
        problems.append("base commit is not a valid object id")

    staged = _patch_listing("staged", body.get("staged_patch"), problems)
    unstaged = _patch_listing("unstaged", body.get("unstaged_patch"), problems)

    untracked, seen = [], set()
    patched = {item["path"].casefold() for item in staged + unstaged}
    files = body.get("files")
    if not isinstance(files, list):
        problems.append("carried file list is malformed")
        files = []
    for item in files:
        path = item.get("path") if isinstance(item, dict) else None
        reason = path_problem(path)
        if reason:
            problems.append(f"untracked file: {reason}: {path!r}")
            continue
        folded = path.casefold()
        if folded in seen:
            # Two names that differ only by case are one file on Windows and macOS.
            problems.append(f"untracked file: {path!r} collides with another carried file")
        elif folded in patched:
            problems.append(f"untracked file: {path!r} collides with a patched file")
        seen.add(folded)
        try:
            data = base64.b64decode(item.get("content_base64", ""), validate=True)
        except (binascii.Error, ValueError, TypeError):
            problems.append(f"untracked file: {path!r} content is not valid base64")
            continue
        if len(data) != item.get("size") or hashlib.sha256(data).hexdigest() != item.get("sha256"):
            problems.append(f"untracked file: {path!r} does not match its recorded size and digest")
            continue
        # v1 bundles written before executable-bit preservation omit mode.  They remain
        # restorable as ordinary files; new bundles always carry one of these two Git modes.
        mode = item.get("mode", 0o100644)
        if mode not in (0o100644, 0o100755):
            problems.append(f"untracked file: {path!r} has an unsupported file mode")
            continue
        untracked.append({"path": path, "size": len(data), "mode": mode})

    notes = [note for note in body.get("notes") or [] if isinstance(note, str)]
    return {"source_machine": body["machine_id"], "repo_id": body["repo_id"],
            "captured_at": body.get("captured_at"), "base_commit": body.get("base_commit"),
            "branch": body.get("branch"), "staged": staged, "unstaged": unstaged,
            "untracked": untracked, "notes": notes, "problems": problems,
            "restorable": not problems}


def base_available(repository, commit: str) -> bool:
    """Whether a local repository holds the commit a restore must start from.

    A patch cannot be applied to a base that is not there, and status metadata alone never
    proves it is. Preview reports this per target checkout instead of promising portability.
    """
    if not COMMIT.fullmatch(str(commit)):
        return False
    result = run_git(repository, ["cat-file", "-e", f"{commit}^{{commit}}"], timeout=10,
                     env={"GIT_OPTIONAL_LOCKS": "0"})
    return result.returncode == 0
