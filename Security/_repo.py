"""What the Security commands share about the repository being scanned. Read-only."""
from __future__ import annotations

import re
from pathlib import Path

from Basic._paths import config_home
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


#: This checkout of gitSpecOps: its git-ignored `.agents/output/` is where the tools' own output
#: lives, whatever repository they scanned, so the person and their agents can read it in place.
TOOL_ROOT = Path(__file__).resolve().parents[1]


def is_ignored(repo: Path, path: Path) -> bool:
    """Whether git would never track `path` in `repo` (it is ignored, or outside the repo)."""
    try:
        relative = Path(path).resolve().relative_to(Path(repo).resolve())
    except ValueError:
        return True  # not inside this repository at all
    return run_git(repo, ["check-ignore", "-q", "--no-index", relative.as_posix()]).returncode == 0


def output_dir(scanned: Path) -> Path:
    """Where reports and plans about `scanned` are written: never anywhere git could publish.

    `<gitSpecOps>/.agents/output/security/<repository name>/` when that folder is ignored in
    this checkout (the normal case), else the per-user gitSpecOps folder. Reports hold the real
    values -- that is their point -- so an output location that is not ignored is never used.
    """

    name = Path(scanned).resolve().name
    candidate = TOOL_ROOT / ".agents" / "output" / "security" / name
    if (TOOL_ROOT / ".agents" / "output").is_dir() and is_ignored(TOOL_ROOT, candidate / "x"):
        return candidate
    return config_home() / "security" / name


def write_report(scanned: Path, stem: str, text: str) -> Path:
    """Write a full, unmasked report about `scanned` into its output folder; return its path."""
    from datetime import datetime

    folder = output_dir(scanned)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{stem}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
    path.write_text(text + "\n", encoding="utf-8")
    return path


def tracked_files(repo: Path) -> list[str] | None:
    proc = run_git(repo, ["ls-files", "-z"])
    if proc.returncode:
        return None
    return [name for name in proc.stdout.split("\0") if name]


def patterns_for(repo: Path, seeds: dict, public_repositories=()) -> dict:
    """Secrets, personal shapes and the runner's identity.

    The repository's own owner name is left out: it is in the repository's URL, so it is public
    identity there, not a finding (the hygiene test stays stricter and still catches the owner
    beside any name that is not a public repository).
    """
    public = [*filter(None, [own_repository_name(repo)]), *public_repositories]
    own = (owner(repo) or "").lower()
    seeds = {kind: [v for v in values if v.lower() != own] for kind, values in seeds.items()}
    return {**SECRETS, **PERSONAL, **identity_patterns(seeds, public)}
