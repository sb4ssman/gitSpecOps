"""Pure Sync Suggester classification and ASCII presentation.

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
PENDING_FLAGS = ("operation", "dirty", "diverged", "ahead", "behind", "stashed", "no_upstream")


def dirty_count(repo: dict) -> int:
    """Staged + unstaged + untracked entries. Untracked counts: it is still unsaved work."""
    return sum(int(repo.get(key) or 0) for key in ("staged", "unstaged", "untracked"))


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
    if ahead is None or behind is None or not repo.get("has_upstream"):
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
    if "diverged" in flags:
        parts.append(f"diverged {ahead}/{behind}")
    elif "ahead" in flags:
        parts.append(f"ahead {ahead}")
    elif "behind" in flags:
        parts.append(f"behind {behind}")
    if "stashed" in flags:
        parts.append(f"{stashes} stash" + ("es" if stashes != 1 else ""))
    if "no_upstream" in flags:
        parts.append("no upstream")
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
    if "diverged" in flags:
        extras.append(f"diverged {ahead}/{behind}")
    elif "ahead" in flags:
        extras.append(f"ahead {ahead}")
    elif "behind" in flags:
        extras.append(f"behind {behind}")
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
    if int(repo.get("stashes") or 0):
        return "stashed", f"review {repo['stashes']} stash(es)"
    if ahead is None or behind is None or not repo.get("has_upstream"):
        return "unknown", "upstream unknown"
    if ahead and behind:
        return "diverged", "human decision"
    if ahead:
        return "ahead", f"PUSH suggested ↑{ahead}"
    if behind:
        return "behind", f"PULL suggested ↓{behind}"
    return "synced", "clean and synchronized"


def render_table(manifest: dict, catalog: dict[str, dict],
                 branches: dict[str, str] | None = None) -> str:
    branches = branches or {}
    rows = []
    for repo in manifest["repositories"]:
        local = catalog.get(repo["repo_id"], {})
        name = local.get("alias") or local.get("display_name") or f"repo:{repo['repo_id'][:8]}"
        _state, action = classify_repository(repo)
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
