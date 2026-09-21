"""Narrow, terminal-first Git actions for an explicitly stopped fleet peer.

The dashboard may eventually invoke these operations, but it must not own a second policy.
This module starts with the one safe group operation: fetch every observed checkout, then
fast-forward only a checkout that is clean and behind-only.  It never commits, pushes, stashes,
resets, merges, rebases, or chooses its way through a conflict.
"""
from __future__ import annotations

from pathlib import Path
import re

from Basic._facts import repo_facts
from Basic._identity import parse_remote_url
from Basic._run import run_git

FETCH_TIMEOUT_SECONDS = 120
PULL_TIMEOUT_SECONDS = 180
NON_INTERACTIVE_GIT_ENV = {
    "GIT_TERMINAL_PROMPT": "0",
    "GCM_INTERACTIVE": "never",
    "GIT_OPTIONAL_LOCKS": "0",
}

# A remote URL is input, not a filesystem layout.  Materialization may construct a new
# destination from its identity, so it accepts only components that are portable on Windows
# and cannot mean "the parent" or a device.  An unusual self-hosted remote can still be cloned
# manually; the safe group operation must not guess a path for it.
_PORTABLE_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_WINDOWS_DEVICES = frozenset({"CON", "PRN", "AUX", "NUL", *
                              (f"COM{number}" for number in range(1, 10)), *
                              (f"LPT{number}" for number in range(1, 10))})


def _safe_component(value: object) -> bool:
    if not isinstance(value, str) or not _PORTABLE_COMPONENT.fullmatch(value):
        return False
    return value.rstrip(". ").upper() not in _WINDOWS_DEVICES


def _safe_materialization_target(destination: Path, host: object, owner: object,
                                 name: object) -> Path | None:
    """Return a destination only when identity and existing links keep it in the library."""
    if not all(_safe_component(value) for value in (host, owner, name)):
        return None
    target = destination / host / owner / name
    try:
        # resolve() follows existing parents, which catches a pre-existing host/owner symlink
        # that would otherwise make a nominally nested clone write outside the chosen library.
        if not target.resolve().is_relative_to(destination.resolve()):
            return None
    except OSError:
        return None
    return target


def _message(proc) -> str:
    """A bounded one-line failure reason; subprocess output is not a UI or log format."""
    value = (proc.stderr or proc.stdout or "git returned a non-zero status").strip()
    return " ".join(value.split())[:240]


def _dirty(path: Path) -> bool | None:
    """True includes untracked files. None means the safety precondition is unreadable."""
    result = run_git(path, ["status", "--porcelain=v1", "--untracked-files=all"],
                     timeout=45, env=NON_INTERACTIVE_GIT_ENV)
    if result.returncode:
        return None
    return bool(result.stdout)


def _fetch(path: Path):
    # Fetch changes only remote-tracking refs. No --prune: a catch-up must not delete even
    # stale local metadata as a side effect of answering whether a pull is safe.
    return run_git(path, ["-c", "credential.interactive=never", "fetch", "--quiet", "origin"],
                   timeout=FETCH_TIMEOUT_SECONDS, env=NON_INTERACTIVE_GIT_ENV)


def _classify(path: Path) -> dict:
    """Freshly classify one checkout after fetch. Every ambiguity becomes a human item."""
    dirty = _dirty(path)
    if dirty is None:
        return {"path": path, "name": path.name, "action": "status_unreadable",
                "detail": "Git could not read status; no action was chosen."}
    facts = repo_facts(path)
    if not facts.get("is_work_tree"):
        return {"path": path, "name": path.name, "action": "not_worktree",
                "detail": "No longer a readable Git worktree."}
    if dirty:
        return {"path": path, "name": path.name, "action": "dirty",
                "detail": "Uncommitted or untracked work is present."}
    if not facts.get("branch"):
        return {"path": path, "name": path.name, "action": "detached",
                "detail": "HEAD is detached, so no branch direction is assumed."}
    if not facts.get("upstream"):
        return {"path": path, "name": path.name, "action": "no_upstream",
                "detail": "The current branch has no upstream."}
    ahead, behind = facts.get("ahead"), facts.get("behind")
    if not isinstance(ahead, int) or not isinstance(behind, int):
        return {"path": path, "name": path.name, "action": "direction_unknown",
                "detail": "Git could not determine ahead/behind after fetching."}
    if behind and not ahead:
        return {"path": path, "name": path.name, "action": "pull", "ahead": ahead,
                "behind": behind, "detail": f"Clean and behind {behind}; fast-forward is safe."}
    if ahead and behind:
        return {"path": path, "name": path.name, "action": "diverged", "ahead": ahead,
                "behind": behind, "detail": f"Ahead {ahead}, behind {behind}; needs a human."}
    if ahead:
        return {"path": path, "name": path.name, "action": "ahead", "ahead": ahead,
                "behind": behind, "detail": f"Ahead {ahead}; it will never be pushed here."}
    return {"path": path, "name": path.name, "action": "current", "ahead": ahead,
            "behind": behind, "detail": "Already current after a fresh fetch."}


def plan_catchup(paths) -> list[dict]:
    """Fetch and plan across local paths. This is safe to run repeatedly and changes no files."""
    plan = []
    for item in sorted((Path(path).resolve() for path in paths), key=lambda path: str(path).casefold()):
        fetched = _fetch(item)
        if fetched.returncode:
            plan.append({"path": item, "name": item.name, "action": "fetch_failed",
                         "detail": _message(fetched)})
        else:
            plan.append(_classify(item))
    return plan


def apply_catchup(plan: list[dict]) -> list[dict]:
    """Apply only planned fast-forward pulls, then recheck each one before claiming success."""
    results = []
    for item in plan:
        if item["action"] != "pull":
            results.append(dict(item))
            continue
        # Explicitly disable recursive submodule updates: this action is about this checkout's
        # current branch, not arbitrary nested repositories.
        pulled = run_git(item["path"], ["-c", "submodule.recurse=false", "pull", "--ff-only"],
                         timeout=PULL_TIMEOUT_SECONDS, env=NON_INTERACTIVE_GIT_ENV)
        if pulled.returncode:
            results.append({**item, "action": "pull_failed", "detail": _message(pulled)})
            continue
        verified = _classify(item["path"])
        if verified["action"] == "current":
            results.append({**verified, "action": "pulled",
                            "detail": "Fast-forwarded and rechecked against the fetched remote."})
        else:
            results.append({**verified, "action": "pull_needs_review",
                            "detail": "Pull returned success, but the final state needs review: "
                                      + verified["detail"]})
    return results


def render_catchup(plan: list[dict], *, applied: bool = False) -> str:
    """Stable, copyable CLI output. Paths deliberately remain local; only basenames are shown."""
    title = "CATCH-UP RESULT" if applied else "CATCH-UP PLAN (fresh fetch completed)"
    lines = [title]
    counts: dict[str, int] = {}
    for item in plan:
        counts[item["action"]] = counts.get(item["action"], 0) + 1
        lines.append(f"  {item['name']}: {item['action'].replace('_', ' ')} — {item['detail']}")
    summary = ", ".join(f"{count} {name.replace('_', ' ')}" for name, count in sorted(counts.items()))
    lines.append(f"\nSummary: {summary or 'no observed repositories'}.")
    if not applied:
        eligible = counts.get("pull", 0)
        lines.append("No working tree changed. " + (
            f"Re-run with --apply --yes to fast-forward the {eligible} eligible checkout(s)."
            if eligible else "There are no safe fast-forward pulls to apply."))
    return "\n".join(lines)


def audit_repositories(paths) -> list[dict]:
    """Read-only remote/worktree audit for a large local working set.

    This is deliberately facts, not an auto-repair tool.  It finds the ordinary reasons a
    collection cannot be treated as one coherent fleet: missing origins/upstreams, unsecured
    plain-HTTP origins, local-only commits and unfinished work.
    """
    rows = []
    for path in sorted((Path(item).resolve() for item in paths), key=lambda item: str(item).casefold()):
        facts = repo_facts(path)
        findings = []
        origin = facts.get("origin")
        if not origin:
            findings.append("no origin")
        elif origin.startswith("http://"):
            findings.append("plain HTTP origin")
        if not facts.get("branch"):
            findings.append("detached HEAD")
        if not facts.get("upstream"):
            findings.append("no upstream")
        if facts.get("ahead"):
            findings.append(f"ahead {facts['ahead']}")
        if facts.get("behind"):
            findings.append(f"behind {facts['behind']}")
        if facts.get("dirty_index") or facts.get("dirty_work_tree"):
            findings.append("tracked changes")
        rows.append({"path": path, "name": path.name, "origin": origin,
                     "findings": findings or ["no audited issue"]})
    return rows


def render_audit(rows: list[dict]) -> str:
    lines = ["FLEET REMOTE AUDIT (read-only)"]
    issues = 0
    for item in rows:
        clean = item["findings"] == ["no audited issue"]
        issues += not clean
        lines.append(f"  {item['name']}: {', '.join(item['findings'])}")
    lines.append(f"\nSummary: {issues} checkout(s) need review; {len(rows) - issues} have no audited issue.")
    lines.append("No remote, branch, index, or working file was changed.")
    return "\n".join(lines)


def plan_materialize(paths, destination) -> list[dict]:
    """Plan a clone-only copy of this machine's observed working set into a new library."""
    destination = Path(destination).resolve()
    rows, seen = [], set()
    for path in sorted((Path(item).resolve() for item in paths), key=lambda item: str(item).casefold()):
        facts = repo_facts(path)
        origin, identity = facts.get("origin"), parse_remote_url(facts.get("origin"))
        if not origin or not identity:
            rows.append({"source": path, "name": path.name, "action": "needs_review",
                         "detail": "No recognizable origin; a local checkout cannot be cloned."})
            continue
        host, owner, name = identity
        target = _safe_materialization_target(destination, host, owner, name)
        if target is None:
            rows.append({"source": path, "name": path.name, "action": "needs_review",
                         "detail": "Origin identity is not a safe destination path."})
            continue
        key = str(target).casefold()
        if key in seen:
            rows.append({"source": path, "name": path.name, "action": "needs_review",
                         "detail": "Another observed checkout maps to the same destination."})
            continue
        seen.add(key)
        if target.exists():
            rows.append({"source": path, "name": path.name, "target": target,
                         "origin": origin, "action": "exists",
                         "detail": "Destination already exists; it is never replaced."})
        else:
            rows.append({"source": path, "name": path.name, "target": target,
                         "library": destination, "origin": origin, "action": "clone",
                         "detail": "Clone the configured origin into the new library."})
    return rows


def apply_materialize(plan: list[dict]) -> list[dict]:
    """Clone only planned missing repositories. Existing destinations are never touched."""
    results = []
    for item in plan:
        if item["action"] != "clone":
            results.append(dict(item)); continue
        target = item["target"]
        if target.exists():
            results.append({**item, "action": "exists",
                            "detail": "Destination appeared after planning; left untouched."})
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        library = item.get("library")
        if not isinstance(library, Path) or not _safe_materialization_target(
                library, target.parent.parent.name, target.parent.name, target.name):
            results.append({**item, "action": "clone_failed",
                            "detail": "Destination changed after planning; left it untouched."})
            continue
        result = run_git(target.parent, ["clone", "--", item["origin"], str(target)], timeout=300,
                         env=NON_INTERACTIVE_GIT_ENV)
        results.append({**item, "action": "cloned" if not result.returncode else "clone_failed",
                        "detail": "Cloned from origin." if not result.returncode else _message(result)})
    return results


def render_materialize(plan: list[dict], *, applied=False) -> str:
    lines = ["MATERIALIZE RESULT" if applied else "MATERIALIZE PLAN"]
    for item in plan:
        lines.append(f"  {item['name']}: {item['action'].replace('_', ' ')} — {item['detail']}")
    if not applied:
        lines.append("No destination was changed. Re-run with --apply --yes to clone only planned missing repositories.")
    return "\n".join(lines)
