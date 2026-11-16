"""What a checkout's uncommitted work is: file names, line counts, and which changes are only
line endings. Never file contents.

Why:          to sync a fleet, a person must see what a machine's "dirty 16" is before deciding
              (the user, 2026-11-16). On one machine every one of 16 files differed only in line
              endings: a Windows backup copied to a Linux-read drive, not work at all.
Reads:        git status and git diff --numstat (with and without --ignore-cr-at-eol) in that
              checkout.
May change:   nothing.
Results:      {"files": [{name, status, added, deleted, line_endings_only}], "count", "eol_only",
              "untracked", "summary"}.
Layer:        Special: this machine, once.
"""
from __future__ import annotations

from pathlib import Path

from Basic._run import run_git

MAX_FILES = 200


def _numstat(path: Path, *extra: str) -> dict[str, tuple[int, int]]:
    result = run_git(path, ["diff", "HEAD", "--numstat", *extra], timeout=60)
    counts = {}
    for line in result.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            added, deleted, name = parts
            counts[name] = (int(added) if added.isdigit() else -1, int(deleted) if deleted.isdigit() else -1)
    return counts


def working_changes(path) -> dict:
    """The uncommitted work in one checkout, by file: what kind of change and how many lines."""
    path = Path(path)
    status = run_git(path, ["status", "--porcelain=v1", "--untracked-files=all"], timeout=60)
    if status.returncode:
        raise ValueError("Git could not read this checkout's status")
    plain, ignoring_eol = _numstat(path), _numstat(path, "--ignore-cr-at-eol")
    files = []
    for line in status.stdout.splitlines():
        code, name = line[:2], line[3:].strip().strip('"')
        if " -> " in name:
            name = name.split(" -> ", 1)[1]
        added, deleted = plain.get(name, (0, 0))
        real = ignoring_eol.get(name)
        files.append({"name": name, "status": "untracked" if code == "??" else code.strip() or "modified",
                      "added": added, "deleted": deleted,
                      "line_endings_only": code != "??" and name in plain and (real is None or real == (0, 0))})
    eol_only = sum(item["line_endings_only"] for item in files)
    untracked = sum(item["status"] == "untracked" for item in files)
    parts = [f"{len(files)} file{'s' if len(files) != 1 else ''} changed"]
    if eol_only:
        parts.append("all only line endings" if eol_only == len(files) else f"{eol_only} only line endings")
    if untracked:
        parts.append(f"{untracked} new and not yet added")
    return {"files": files[:MAX_FILES], "count": len(files), "eol_only": eol_only, "untracked": untracked,
            "summary": ", ".join(parts) if files else "no uncommitted work"}
