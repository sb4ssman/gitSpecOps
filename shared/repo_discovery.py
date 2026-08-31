"""
repo_discovery
==============

SHARED SPECIAL OPERATION (read-only): find Git repositories on disk. Pure filesystem
scan — no git subprocess, no network, never mutates anything. Detects work trees
(`.git` dir), linked worktrees/submodules (`.git` FILE with a "gitdir:" pointer), and
bare repos (HEAD + objects/ + refs/, e.g. "name.git"). The walk never follows symlinks,
stays on one filesystem by default, and prunes heavy/irrelevant dirs.

Shared rule: a method lives in `shared/` once two of the three special operations need
it. Stdlib only; no imports from tool folders; no policy.

Standalone (the machine / root scanner):

    python shared/repo_discovery.py <root> [--json] [--max-depth N] [--hidden]
        [--cross-filesystems] [--no-skip]
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# Never descended into. Overridable per call / via --no-skip.
DEFAULT_SKIP_NAMES = frozenset({
    ".git", ".svn", ".hg", "__pycache__", ".tox", ".nox", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", ".venv", "venv", "env", "node_modules",
    "bower_components", "site-packages", "dist-packages", ".cache", ".cargo",
    ".rustup", ".npm", ".nvm", ".nuget", ".dotnet", ".gradle", ".m2", ".android",
    ".docker", ".terraform", "AppData", "Library", ".Trash",
    "$RECYCLE.BIN", "System Volume Information",
})


@dataclass
class RepoHit:
    """A discovered repository. kind: 'worktree' | 'gitfile' | 'bare'."""
    path: str
    kind: str
    gitdir: str | None = None  # .git dir, gitdir: pointer target, or the bare dir itself


def has_git_marker(path: Path) -> bool:
    return (path / ".git").exists()


def is_bare_repo(path: Path) -> bool:
    """HEAD + objects/ + refs/ heuristic — same shape as a `--mirror` clone."""
    return (path / "HEAD").is_file() and (path / "objects").is_dir() and (path / "refs").is_dir()


def classify(path: Path) -> RepoHit | None:
    """Return a RepoHit when path is a repository, else None."""
    marker = path / ".git"
    if marker.is_dir():
        return RepoHit(path=str(path), kind="worktree", gitdir=str(marker))
    if marker.is_file():
        gitdir = None
        try:
            first = marker.read_text(encoding="utf-8", errors="replace").strip()
            if first.lower().startswith("gitdir:"):
                gitdir = first.split(":", 1)[1].strip() or None
        except OSError:
            pass
        return RepoHit(path=str(path), kind="gitfile", gitdir=gitdir)
    if is_bare_repo(path):
        return RepoHit(path=str(path), kind="bare", gitdir=str(path))
    return None


def list_child_dirs(root: Path) -> list[Path]:
    """Sorted direct child directories of root (the archive tools' scan shape)."""
    return sorted([item for item in root.iterdir() if item.is_dir()],
                  key=lambda item: item.name.lower())


def is_hidden(path: Path) -> bool:
    return path.name.startswith(".")

def find_repos(root: Path, max_depth: int | None = None, include_hidden: bool = False,
               cross_filesystems: bool = False, skip_names: frozenset | set | None = None,
               progress: callable | None = None) -> list[RepoHit]:
    """Walk root; return every repository found, sorted by path.

    max_depth None = unlimited. include_hidden: also scan dotted dirs (never entering
    `.git` internals). cross_filesystems False = stay on root's device (like find -xdev).
    progress: optional callback progress(scanned_dirs, found, current_dir).
    """
    if skip_names is None:
        skip_names = DEFAULT_SKIP_NAMES
    root = Path(root)
    if not root.is_dir():
        raise NotADirectoryError(str(root))
    try:
        root_dev = root.stat().st_dev
    except OSError:
        root_dev = None
    hits: list[RepoHit] = []
    scanned = 0
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        current, depth = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue
        for entry in entries:
            try:
                if not entry.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            scanned += 1
            name = entry.name
            if name in skip_names or (not include_hidden and name.startswith(".")):
                continue
            if not cross_filesystems and root_dev is not None:
                try:
                    if entry.stat(follow_symlinks=False).st_dev != root_dev:
                        continue
                except OSError:
                    continue
            child = Path(entry.path)
            hit = classify(child)
            if hit is not None:
                hits.append(hit)
            if max_depth is None or depth + 1 <= max_depth:
                stack.append((child, depth + 1))
        if progress is not None:
            progress(scanned, len(hits), str(current))
    hits.sort(key=lambda h: h.path)
    return hits


def _progress_throttle(interval: float = 2.0):
    """Progress callback printing to stderr at most every `interval` seconds."""
    state = {"last": 0.0}

    def show(scanned: int, found: int, current: str) -> None:
        now = time.monotonic()
        if now - state["last"] >= interval:
            state["last"] = now
            print(f"  scanned {scanned} dirs, found {found} repos — in {current}", file=sys.stderr)

    return show


def main(argv: list[str]) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Find Git repositories under a root (read-only).")
    parser.add_argument("root", nargs="?", default=".", help="root to walk (default: cwd)")
    parser.add_argument("--json", action="store_true", help="emit a JSON manifest")
    parser.add_argument("--max-depth", type=int, default=None, help="limit walk depth")
    parser.add_argument("--hidden", action="store_true", help="also scan dotted directories")
    parser.add_argument("--cross-filesystems", action="store_true", help="follow other mounts")
    parser.add_argument("--no-skip", action="store_true", help="do not skip heavy/known dirs")
    args = parser.parse_args(argv)
    try:
        hits = find_repos(Path(args.root), max_depth=args.max_depth,
                          include_hidden=args.hidden, cross_filesystems=args.cross_filesystems,
                          skip_names=set() if args.no_skip else None,
                          progress=None if args.json else _progress_throttle())
    except NotADirectoryError as exc:
        print(f"Not a directory: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"root": str(Path(args.root).resolve()),
                          "repos": [h.__dict__ for h in hits]}, indent=2))
        return 0
    kinds: dict[str, int] = {}
    for hit in hits:
        kinds[hit.kind] = kinds.get(hit.kind, 0) + 1
        print(f"  [{hit.kind:<8}] {hit.path}")
    summary = ", ".join(f"{k}: {v}" for k, v in sorted(kinds.items())) or "none"
    print(f"\nTotal: {len(hits)} repos  ({summary})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
