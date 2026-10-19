"""What the Security commands share about the repository being scanned. Read-only."""
from __future__ import annotations

import re
from pathlib import Path

from Basic._run import run_git
from Security._patterns import PERSONAL, SECRETS, identity_patterns


def origin_url(repo: Path) -> str:
    proc = run_git(repo, ["remote", "get-url", "origin"])
    return proc.stdout.strip().rstrip("/") if proc.returncode == 0 else ""


def own_repository_name(repo: Path) -> str | None:
    """This repository's own name on its remote: its clone URL is public identity, not a leak."""
    name = re.split(r"[/:]", origin_url(repo))[-1]
    return name[:-4] if name.endswith(".git") else (name or None)


def owner(repo: Path) -> str | None:
    """The owner segment of this repository's origin: public identity, never rewritten."""
    parts = re.split(r"[/:]", origin_url(repo))
    return parts[-2] if len(parts) >= 2 and parts[-2] else None


def tracked_files(repo: Path) -> list[str] | None:
    proc = run_git(repo, ["ls-files", "-z"])
    if proc.returncode:
        return None
    return [name for name in proc.stdout.split("\0") if name]


def patterns_for(repo: Path, seeds: dict, public_repositories=()) -> dict:
    """Secrets, personal shapes and the runner's identity, excusing this repository's own name."""
    public = [*filter(None, [own_repository_name(repo)]), *public_repositories]
    return {**SECRETS, **PERSONAL, **identity_patterns(seeds, public)}
