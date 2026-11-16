"""Pure fleet classification and ASCII presentation.

`classify_repository` returns a single headline state, which is what severity ordering needs.
But a headline necessarily hides everything behind it: a repository that is both dirty and
ahead reports only "dirty", and the unpushed commits vanish from view. That is a real way to
lose information a person needed.

So the headline is for ordering only. Anything that *renders or advises* uses
`repository_flags` / `describe_repository`, which keep every fact that is true at once.
"""

from __future__ import annotations

# Facts that mean "there is something outstanding here". Order is display order, not
# precedence — every one that applies is reported.
PENDING_FLAGS = ("operation", "dirty", "no_remote", "diverged", "ahead", "unpushed", "behind",
                 "stashed", "no_upstream")


def dirty_count(repo: dict) -> int:
    """Staged + unstaged + untracked entries. Untracked counts: it is still unsaved work."""
    return sum(int(repo.get(key) or 0) for key in ("staged", "unstaged", "untracked"))


def elsewhere_unpushed(repo: dict) -> int:
    """Commits on no remote that the current branch's `ahead` does not already account for:
    work on other branches or tags, or on a branch with no upstream."""
    unpushed = repo.get("unpushed")
    if not isinstance(unpushed, int) or repo.get("has_remote", True) is False:
        return 0
    return max(0, unpushed - int(repo.get("ahead") or 0))


def repository_flags(repo: dict) -> frozenset[str]:
    """Every fact true of this repository at once, with nothing suppressed by precedence."""
    ahead, behind = repo.get("ahead"), repo.get("behind")
    flags = set()
    if repo.get("operation"):
        flags.add("operation")
    if dirty_count(repo):
        flags.add("dirty")
    if int(repo.get("stashes") or 0):
        flags.add("stashed")
    if elsewhere_unpushed(repo):
        flags.add("unpushed")
    if repo.get("has_remote", True) is False:
        # No remote at all: "no upstream" would undersell it -- this is the only copy.
        flags.add("no_remote")
    elif ahead is None or behind is None or not repo.get("has_upstream"):
        flags.add("no_upstream")
    else:
        if ahead and behind:
            flags.add("diverged")
        elif ahead:
            flags.add("ahead")
        elif behind:
            flags.add("behind")
    if not flags:
        flags.add("clean")
    return frozenset(flags)


def describe_repository(repo: dict) -> str:
    """Compact description of everything outstanding, e.g. "dirty 3, ahead 1, 1 stash"."""
    flags = repository_flags(repo)
    ahead, behind = repo.get("ahead") or 0, repo.get("behind") or 0
    stashes = int(repo.get("stashes") or 0)
    parts = []
    if "operation" in flags:
        parts.append(str(repo.get("operation")))
    if "dirty" in flags:
        parts.append(f"dirty {dirty_count(repo)}")
    if "no_remote" in flags:
        parts.append("no remote")
    if "diverged" in flags:
        parts.append(f"diverged {ahead}/{behind}")
    elif "ahead" in flags:
        parts.append(f"ahead {ahead}")
    elif "behind" in flags:
        parts.append(f"behind {behind}")
    if "unpushed" in flags:
        parts.append(f"{elsewhere_unpushed(repo)} unpushed on other branches/tags")
    if "stashed" in flags:
        parts.append(f"{stashes} stash" + ("es" if stashes != 1 else ""))
    if "no_upstream" in flags:
        parts.append("no upstream")
    checkouts = int(repo.get("checkouts") or 1)
    if checkouts > 1:
        parts.append(f"{checkouts} checkouts")
    return ", ".join(parts) if parts else "clean"


def secondary_facts(repo: dict, headline: str) -> str:
    """What the headline state leaves out, rendered for appending to advice.

    This is the guard against precedence hiding relevant state: a dirty repository that is
    also three commits ahead must say so, or the person only learns half of what is waiting.
    """
    flags = repository_flags(repo) - {headline, "clean"}
    ahead, behind = repo.get("ahead") or 0, repo.get("behind") or 0
    stashes = int(repo.get("stashes") or 0)
    extras = []
    if "operation" in flags:
        extras.append(f"{repo.get('operation')} in progress")
    if "dirty" in flags:
        extras.append(f"dirty {dirty_count(repo)}")
    if "no_remote" in flags:
        extras.append("no remote")
    if "diverged" in flags:
        extras.append(f"diverged {ahead}/{behind}")
    elif "ahead" in flags:
        extras.append(f"ahead {ahead}")
    elif "behind" in flags:
        extras.append(f"behind {behind}")
    if "unpushed" in flags:
        extras.append(f"{elsewhere_unpushed(repo)} unpushed on other branches/tags")
    if "stashed" in flags:
        extras.append(f"{stashes} stash" + ("es" if stashes != 1 else ""))
    return ", ".join(extras)


def classify_repository(repo: dict) -> tuple[str, str]:
    """The single headline state, used for severity ordering. See the module docstring."""
    dirty = sum(int(repo.get(key) or 0) for key in ("staged", "unstaged", "untracked"))
    ahead, behind = repo.get("ahead"), repo.get("behind")
    if repo.get("operation"):
        return "operation", f"finish {repo['operation']}"
    if dirty:
        return "dirty", "COMMIT or preserve"
    if repo.get("has_remote", True) is False:
        return "local_only", "only copy: ADD A REMOTE and push"
    if int(repo.get("stashes") or 0):
        return "stashed", f"review {repo['stashes']} stash(es)"
    if ahead is None or behind is None or not repo.get("has_upstream"):
        return "unknown", "upstream unknown"
    if ahead and behind:
        return "diverged", "human decision"
    if ahead:
        return "ahead", f"PUSH suggested ↑{ahead}"
    if elsewhere_unpushed(repo):
        return "unpushed", f"PUSH other branches/tags ({elsewhere_unpushed(repo)} on no remote)"
    if behind:
        return "behind", f"PULL suggested ↓{behind}"
    return "synced", "clean and synchronized"


def security_notices(records):
    """Local check status without suppressing sync facts or implying execution clearance."""
    groups = {}
    for entry in records:
        groups.setdefault(entry["repo_id"], set()).add(entry["security"]["check_status"])
    result = {}
    for repo_id, statuses in groups.items():
        if statuses - {"passed", "incomplete", "blocked", "review-required"}:
            statuses.add("incomplete")
        status = next((value for value in ("incomplete", "blocked", "review-required") if value in statuses), "passed")
        result[repo_id] = ("security advisory passed; recheck on action" if status == "passed" else
                           f"SECURITY {status}; review before commit/push")
    return result


def library_tree(roots, observation, *, everything: bool = False) -> list[tuple[str, str]]:
    """This machine's repositories for a person at a terminal: library folder, then the folder
    inside it (an org folder, say), then each repository that needs something; clean ones are
    counted unless `everything`. Lines are (text, tone); the screen wraps them to its width. Local
    only: it shows this machine's own folders and is never published (2026-11-15: the wide table
    wrapped into rows of dashes, and 188 rows were too many to read)."""
    from pathlib import Path

    roots = [Path(root) for root in roots]
    groups: dict[tuple[str, str], list[tuple[str, str, str, bool]]] = {}
    for repo, location in zip(observation.repositories, observation.locations):
        location = Path(location)
        root = next((r for r in roots if location == r or r in location.parents), location.parent)
        parts = location.relative_to(root).parts if location != root else (location.name,)
        folder = parts[0] if len(parts) > 1 else ""
        name = "/".join(parts[1:]) if len(parts) > 1 else parts[0]
        state, action = classify_repository(repo)
        branch_id = repo.get("branch_id")
        branch = "(detached)" if not branch_id else observation.branches.get(branch_id, "")
        detail = f"{describe_repository(repo)}: {action}" if state != "synced" else "clean"
        groups.setdefault((str(root), folder), []).append((name, branch, detail, state != "synced"))
    lines: list[tuple[str, str]] = []
    last_root = None
    for (root, folder), items in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1].casefold())):
        if root != last_root:
            lines.append(("", "text"))
            lines.append((root, "strong"))
            last_root = root
        attention = [item for item in items if item[3]]
        heading = folder or "(directly in this folder)"
        summary = (f"{len(items)} repositor{'y' if len(items) == 1 else 'ies'}, "
                   + (f"{len(attention)} need{'s' if len(attention) == 1 else ''} something"
                      if attention else "all clean"))
        lines.append((f"  {heading}  ({summary})", "warning" if attention else "success"))
        for name, branch, detail, needs in sorted(items, key=lambda item: item[0].casefold()):
            if needs or everything:
                lines.append((f"      {name}" + (f"  [{branch}]" if branch else "") + f"  {detail}",
                              "text" if needs else "muted"))
    return lines


def render_table(manifest: dict, catalog: dict[str, dict],
                 branches: dict[str, str] | None = None, *, security=None) -> str:
    branches = branches or {}
    notices = security_notices(security or [])
    rows = []
    for repo in manifest["repositories"]:
        local = catalog.get(repo["repo_id"], {})
        name = local.get("alias") or local.get("display_name") or f"repo:{repo['repo_id'][:8]}"
        _state, action = classify_repository(repo)
        if security is not None:
            action = notices.get(repo["repo_id"], "security unchecked") + "; " + action
        state = describe_repository(repo)
        branch = repo.get("branch_id")
        # A branch this machine has seen resolves to its name; one only a peer has stays an
        # opaque id, exactly as an unknown repository does.
        label = "(detached)" if not branch else branches.get(branch, f"branch:{branch[:8]}")
        rows.append((name, label, state, action))
    widths = [len("Repository"), len("Branch"), len("State"), len("Advice")]
    for row in rows:
        widths = [max(width, len(str(value))) for width, value in zip(widths, row)]
    header = ("Repository", "Branch", "State", "Advice")
    format_row = lambda row: "  ".join(str(value).ljust(width) for value, width in zip(row, widths))
    lines = [format_row(header), format_row(tuple("-" * width for width in widths))]
    lines.extend(format_row(row) for row in rows)
    return "\n".join(lines)
