"""Branch and stash inspection and an attended, tracked-files stash."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from Basic._objects import git_output
from Basic._run import run_git
from Special._runtime.files import traverses_link

LIMIT = 50


def inspect_checkout(repo, kind):
    if kind == "branches":
        fields = "%(HEAD)%00%(refname:short)%00%(objectname)%00%(upstream:short)%00%(upstream:track)"
        lines = git_output(repo, ["for-each-ref", "--count=51", f"--format={fields}", "refs/heads"]).splitlines()
        rows = []
        for line in lines[:LIMIT]:
            current, branch, tip, upstream, divergence = line.split("\0")
            rows.append({"branch": branch, "tip": tip, "upstream": upstream, "divergence": divergence,
                         "current": current == "*"})
        return {"ok": True, "branches": rows, "cut": len(lines) > LIMIT}
    lines = git_output(repo, ["stash", "list", "-51", "--format=%gd%x00%H%x00%gs"]).splitlines()
    rows = []
    for line in lines[:LIMIT]:
        ref, oid, subject = line.split("\0", 2)
        rows.append({"ref": ref, "oid": oid, "subject": subject})
    return {"ok": True, "stashes": rows, "cut": len(lines) > LIMIT}


def _stash_state(repo):
    for entry in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "sequencer"):
        marker = Path(git_output(repo, ["rev-parse", "--git-path", entry]).strip())
        if (repo / marker).exists():
            raise ValueError("Finish the current Git operation before stashing.")
    head = git_output(repo, ["rev-parse", "--verify", "HEAD"]).strip()
    branch = git_output(repo, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()
    records = git_output(repo, ["status", "--porcelain=v2", "-z", "--no-renames", "--untracked-files=normal"]).split("\0")
    tracked, untracked = [], 0
    for entry in records:
        if entry.startswith("? "):
            untracked += 1
        elif entry.startswith(("u ", "2 ")):
            raise ValueError("Unmerged entries or renames need local review before stashing.")
        elif entry.startswith("1 "):
            parts = entry.split(" ", 8)
            if parts[2].startswith("S") or traverses_link(repo / parts[-1]):
                raise ValueError("Submodule or linked changes need local review before stashing.")
            tracked.append(parts[-1])
    flags = ["--binary", "--full-index", "--no-ext-diff", "--no-textconv", "--no-renames"]
    staged = git_output(repo, ["diff", *flags, "--cached", "--"])
    unstaged = git_output(repo, ["diff", *flags, "--"])
    return (head, branch, records, staged, unstaged), tracked, untracked


def stash_checked(repo, message, approve=None):
    if not isinstance(message, str) or not message.strip() or len(message) > 200 or not message.isprintable():
        raise ValueError("Write a one-line stash description of up to 200 characters.")
    repo = Path(repo).resolve()
    state, files, untracked = _stash_state(repo)
    if not files:
        return {"ok": True, "status": "nothing-to-stash", "files": [], "untracked": untracked}
    plan_id = hashlib.sha256(json.dumps([str(repo), state, message]).encode()).hexdigest()
    if approve is None:
        return {"ok": True, "status": "stash-ready", "plan_id": plan_id, "files": files[:LIMIT],
                "untracked": untracked, "count": len(files)}
    if approve != plan_id or _stash_state(repo)[0] != state:
        return {"ok": False, "status": "stale"}
    previous = run_git(repo, ["rev-parse", "--verify", "--quiet", "refs/stash"]).stdout.strip()
    saved = run_git(repo, ["stash", "push", "--message", message], timeout=120)
    current = run_git(repo, ["rev-parse", "--verify", "--quiet", "refs/stash"]).stdout.strip()
    applied = bool(current and current != previous)
    return {"ok": not saved.returncode and applied, "status": "stashed" if not saved.returncode and applied
            else "stash-needs-review" if applied else "failed", "applied": applied}
