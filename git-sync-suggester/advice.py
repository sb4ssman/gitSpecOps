"""Pure Sync Suggester classification and initial ASCII presentation."""

from __future__ import annotations


def classify_repository(repo: dict) -> tuple[str, str]:
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
        state, action = classify_repository(repo)
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
