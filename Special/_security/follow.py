"""After a history rewrite: move this machine's clones onto the new history; fix quoted commit ids.

Why:          a clone made before a rewrite still holds the old history, and pushing from it
              would publish the old history again. Commit ids quoted in files (logs, notes,
              changelogs) still name commits that no longer exist.
Reads:        each checkout's branch, upstream, status and remote-tracking reflogs; the rewrite
              workspace's `mirror.git/filter-repo/commit-map` (written by clean_history).
May change:   with confirmation, `git reset --keep` of a checkout's branch onto its rewritten
              upstream (never --hard: an edit is never overwritten). `relink --write` edits
              quoted ids in tracked text files and leaves them for review: nothing is committed
              or pushed here (Special/commit_repo.py and push_repo.py do that, checked).
Results:      plans and results on stdout.
Layer:        Special: this machine, once.
Status:       working. Ported from version 1 (`_archive/Security/_rewrite.py`), whose `finish`
              committed and pushed by default; that step is now the checked commit and push.
"""
from __future__ import annotations

import bisect
import re
import sys
from pathlib import Path

from Basic._confirm import prompt_yes_no
from Basic._discovery import find_repos
from Basic._run import run_git

FETCH_TIMEOUT_SECONDS = 3600
MAP_LIMIT_BYTES = 4 * 1024 * 1024
#: A commit id as people quote one: 7 to 40 lowercase hex digits standing alone.
SHA_TOKEN = re.compile(r"(?<![0-9A-Za-z])[0-9a-f]{7,40}(?![0-9A-Za-z])")


def commit_map(workspace: Path) -> dict[str, str]:
    """`{old commit: new commit}` from a rewritten workspace (filter-repo's own record)."""
    path = Path(workspace) / "mirror.git" / "filter-repo" / "commit-map"
    if not path.is_file():
        raise ValueError(f"no commit map in {workspace}: run the cleanup's apply step first")
    if path.stat().st_size > MAP_LIMIT_BYTES:
        raise ValueError("commit map exceeds its limit")
    mapping = {}
    for line in path.read_text(encoding="ascii").splitlines()[1:]:
        parts = line.split()
        if len(parts) == 2 and parts[0] != parts[1] and set(parts[1]) != {"0"}:
            mapping[parts[0]] = parts[1]
    return mapping


def references(text: str, mapping: dict[str, str], olds: list[str] | None = None) -> list:
    """`(offset, old token, new token)` for every quoted id naming exactly one old commit."""
    olds = olds if olds is not None else sorted(mapping)
    found = []
    for match in SHA_TOKEN.finditer(text):
        token = match.group(0)
        index = bisect.bisect_left(olds, token)
        hits = [old for old in olds[index:index + 2] if old.startswith(token)]
        if len(hits) == 1:
            found.append((match.start(), token, mapping[hits[0]][:len(token)]))
    return found


def tracked_files(checkout: Path) -> list[str]:
    listed = run_git(checkout, ["ls-files", "-z"])
    if listed.returncode:
        raise ValueError(f"{checkout} is not a readable Git checkout")
    return [name for name in listed.stdout.split("\0") if name]


def relink(workspaces, checkout: Path, *, write: bool = False,
           edited: list | None = None) -> tuple[list[str], int]:
    """(report lines, references found) in `checkout`'s tracked text files; edits when `write`.

    Several workspaces' maps are merged: repositories rewritten together quote each other."""
    workspaces = [workspaces] if isinstance(workspaces, (str, Path)) else list(workspaces)
    mapping = {old: new for workspace in workspaces for old, new in commit_map(workspace).items()}
    olds = sorted(mapping)
    checkout = Path(checkout)
    history = set(run_git(checkout, ["rev-list", "HEAD"]).stdout.split())
    if history & set(mapping):
        raise ValueError(f"{checkout} is still on the old history: run `follow` first")
    lines, total = [], 0
    for name in tracked_files(checkout):
        path = checkout / name
        try:
            raw = path.read_bytes()
            if b"\0" in raw[:8192]:
                continue
            text = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        found = references(text, mapping, olds)
        if not found:
            continue
        total += len(found)
        for offset, old, new in found:
            lines.append(f"  {name}:{text.count(chr(10), 0, offset) + 1}: {old} -> {new}")
        if write:
            for offset, old, new in reversed(found):
                text = text[:offset] + new + text[offset + len(old):]
            path.write_bytes(text.encode("utf-8"))
            if edited is not None:
                edited.append(name)
    return lines, total


def published_before(repo: Path, new_tip: str) -> list[str]:
    """Every value a remote-tracking ref held that is not part of the new history.

    The reflog files are read directly, old and new value of every line: a fresh clone keeps
    no `origin/main` log of its own, so the value it was cloned at survives only as the *old*
    value of the first fetch. Commits reachable from none of these were never pushed."""
    logs = run_git(repo, ["rev-parse", "--git-path", "logs/refs/remotes"]).stdout.strip()
    folder = Path(logs) if Path(logs).is_absolute() else repo / logs
    values = []
    for path in sorted(folder.rglob("*")) if folder.is_dir() else []:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            values += [value for value in line.split()[:2]
                       if len(value) >= 40 and set(value) != {"0"} and value not in values]
    current = run_git(repo, ["for-each-ref", "--format=%(objectname)", "refs/remotes"]).stdout
    values += [value for value in current.split() if value not in values]
    # Not part of the new history = not one of its ancestors. (Sharing no commit at all is too
    # strict: a rewrite keeps every commit before its first change, often the root.)
    return [value for value in values
            if run_git(repo, ["merge-base", "--is-ancestor", value, new_tip]).returncode == 1]


def assess(repo: Path, *, fetch: bool = True) -> dict:
    """What `follow` would do for one checkout. Changes nothing but a fetch.

    `action` is "move" (nothing would be lost), "current" (nothing to follow), "skip" (no
    upstream) or "refuse" (with `why`: something could be lost, or nothing proves otherwise)."""
    repo = Path(repo).resolve()
    found = {"repo": repo, "action": "refuse", "why": "", "hint": "", "stale": []}
    branch = run_git(repo, ["branch", "--show-current"]).stdout.strip()
    found["branch"] = branch
    if not branch:
        found["why"] = "detached HEAD: check out the branch to move first"
        return found
    if fetch:
        fetched = run_git(repo, ["fetch", "--prune"], timeout=FETCH_TIMEOUT_SECONDS)
        if fetched.returncode:
            found["why"] = "fetch failed"
            return found
    upstream = run_git(repo, ["rev-parse", "--abbrev-ref", "--symbolic-full-name",
                              "@{upstream}"]).stdout.strip()
    found["upstream"] = upstream
    if not upstream:
        found.update(action="skip", why=f"{branch} has no upstream")
        return found
    # "Current" means one history contains the other (a normal pull or push handles it). Merely
    # sharing *some* commit is not enough: a rewrite keeps every commit before its first change
    # (often the root), so an old clone still shares history with the rewritten upstream.
    if (run_git(repo, ["merge-base", "--is-ancestor", upstream, "HEAD"]).returncode == 0
            or run_git(repo, ["merge-base", "--is-ancestor", "HEAD", upstream]).returncode == 0):
        found.update(action="current", why=f"{branch} and {upstream} are on one history")
        return found
    if run_git(repo, ["status", "--porcelain", "--untracked-files=no"]).stdout.strip():
        found["why"] = ("uncommitted changes to tracked files: commit or stash them first (or "
                        "re-clone into a new folder and carry them over)")
        return found
    new_tip = run_git(repo, ["rev-parse", upstream]).stdout.strip()
    published = published_before(repo, new_tip)
    if not published:
        found["why"] = ("no record of what the remote held before the rewrite, so unpushed "
                        "work cannot be ruled out: re-clone into a new folder and compare")
        return found
    alone = run_git(repo, ["rev-list", "HEAD", "--not", *published]).stdout.split()
    if alone:
        subjects = [run_git(repo, ["log", "-1", "--format=%h %s", sha]).stdout.strip()
                    for sha in alone[:20]]
        found["why"] = (f"{len(alone)} commit(s) on {branch} were never on the remote; moving "
                        "would hide them:\n" + "\n".join(f"    {s}" for s in subjects))
        base = run_git(repo, ["merge-base", "HEAD", *published]).stdout.strip()
        if base:
            found["hint"] = ("check their author identity, then replay them onto the new "
                             f"history with: git rebase --onto {upstream} {base[:12]} {branch}")
        return found
    found["stale"] = [other for other in run_git(repo, ["for-each-ref", "--format=%(refname:short)",
                                                        "refs/heads", "refs/tags"]).stdout.split()
                      if other != branch
                      and run_git(repo, ["merge-base", other, "HEAD"]).returncode == 0
                      and run_git(repo, ["merge-base", other, upstream]).returncode]
    found.update(action="move", old_tip=run_git(repo, ["rev-parse", "--short", "HEAD"]).stdout.strip(),
                 new_tip=new_tip[:7])
    return found


def move(found: dict) -> bool:
    """`git reset --keep` onto the upstream, for an assessment that said "move"."""
    moved = run_git(found["repo"], ["reset", "--keep", found["upstream"]])
    if moved.returncode:
        print("  git reset --keep refused; nothing was overwritten.", file=sys.stderr)
        return False
    if found["stale"]:
        print("  still pointing into the old history (pushing any of these would publish it "
              "again); delete or move each: " + ", ".join(found["stale"]))
    return True


def follow(repo: Path, *, fetch: bool = True, assume_yes: bool = False) -> int:
    """Move one pre-rewrite clone's checked-out branch onto its rewritten upstream, or refuse."""
    found = assess(repo, fetch=fetch)
    if found["action"] in ("current", "skip"):
        print(f"{found['why']}: nothing to follow"
              + (" (a normal pull handles it)." if found["action"] == "current" else "."))
        return 0 if found["action"] == "current" else 2
    if found["action"] == "refuse":
        print(f"Nothing was changed: {found['why']}", file=sys.stderr)
        if found["hint"]:
            print(found["hint"], file=sys.stderr)
        return 1
    print(f"Every commit on {found['branch']} was on the remote before the rewrite.")
    print(f"Move {found['branch']}: {found['old_tip']} (old history) -> {found['new_tip']} with "
          "`git reset --keep`.")
    if not assume_yes and not prompt_yes_no("Move it now?", default=False):
        print("Nothing was changed.")
        return 1
    if not move(found):
        return 1
    print(f"Moved {found['branch']} onto {found['upstream']}. The old commits stay in this "
          "clone's reflog, on no branch, until Git expires them; nothing pushes them.")
    return 0


def repositories_under(paths, *, match=(), depth: int = 3) -> list[Path]:
    """Every checkout at or under `paths` whose origin URL contains one of `match` (any, when
    none is given)."""
    found = []
    for path in (Path(p).resolve() for p in paths):
        if (path / ".git").exists():
            found.append(path)
        else:
            found += [Path(hit.path) for hit in find_repos(path, max_depth=depth) if hit.kind != "bare"]
    match = [text.lower() for text in match]
    return [repo for repo in dict.fromkeys(found)
            if not match or any(text in run_git(repo, ["remote", "get-url", "origin"]).stdout.lower()
                                for text in match)]


def follow_many(paths, *, match=(), depth: int = 3, fetch: bool = True,
                assume_yes: bool = False) -> int:
    """Assess every checkout under `paths`, show all, ask once, then move only the safe ones."""
    repos = repositories_under(paths, match=match, depth=depth)
    if not repos:
        print("No matching repositories found.", file=sys.stderr)
        return 2
    print(f"Checking {len(repos)} repositor{'y' if len(repos) == 1 else 'ies'} (fetching each)...")
    results = [assess(repo, fetch=fetch) for repo in repos]
    moves = [r for r in results if r["action"] == "move"]
    refused = [r for r in results if r["action"] == "refuse"]
    current = [r for r in results if r["action"] in ("current", "skip")]
    print(f"\nAlready current or nothing to follow: {len(current)}")
    if refused:
        print(f"Refused; nothing will change in these ({len(refused)}):")
        for r in refused:
            print(f"  {r['repo']}: {r['why']}")
            if r["hint"]:
                print(f"    {r['hint']}")
    if not moves:
        print("Nothing to move.")
        return 1 if refused else 0
    print(f"To move onto the rewritten history ({len(moves)}):")
    print("\n".join(f"  {r['repo']}  {r['branch']}: {r['old_tip']} -> {r['new_tip']}" for r in moves))
    if not assume_yes and not prompt_yes_no(f"Move these {len(moves)} now?", default=False):
        print("Nothing was changed.")
        return 1
    failed = sum(not move(r) for r in moves)
    print(f"\nMoved {len(moves) - failed}; refused {len(refused)}; failed {failed}. The old "
          "commits stay in each clone's reflog, on no branch; nothing pushes them.")
    return 1 if failed or refused else 0
