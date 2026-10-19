"""Scan a repository's tracked files for secrets and personal data. Read-only.

    python Security/scan_tree.py [REPO] [--public-repo NAME] [--exclude PATH] [--online]
                                 [--no-tailnet] [--show-values]

What the public can read *today*: every tracked file, whole (no line is truncated), against the
shared rules in `Security/_patterns.py` plus the identity of the person running it (git and gh
identity, host and home-folder name, tailnet machine names and addresses; with `--online`,
the GitHub organizations the gh login belongs to). Values are masked unless `--show-values` is
given. Exit status 1 when anything is found.

For what the repository's *history* publishes, see `scan_history.py`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Basic._console import enable_unicode_output  # noqa: E402
from Security._patterns import (PERSONAL, SECRETS, find, identity_patterns,  # noqa: E402
                                line_of, mask)
from Security._repo import own_repository_name, tracked_files  # noqa: E402
from Security._seeds import identity_seeds  # noqa: E402

EFFECT = "none"

#: Where a project's owner is *meant* to appear: copyright and package metadata.
AUTHORSHIP_FILES = frozenset({"NOTICE", "LICENSE", "pyproject.toml", "package.json", "setup.py",
                              "setup.cfg", "Cargo.toml"})


def scan_files(repo: Path, names: list[str], seeds: dict, public_repositories=(),
               exclude=frozenset(), show_values: bool = False) -> list[str]:
    """Findings as printable lines. Identity values are masked unless `show_values`."""
    general = {**SECRETS, **PERSONAL}
    personal = identity_patterns(seeds, public_repositories)
    findings = []
    for name in names:
        if name in exclude:
            continue
        try:
            text = (repo / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        hits = find(text, general)
        if Path(name).name not in AUTHORSHIP_FILES:
            hits += find(text, personal)
        for hit in hits:
            # Masked by default -- a found token printed whole lands in logs and pastes.
            shown = hit.value if show_values else mask(hit.value)
            findings.append(f"{name}:{line_of(text, hit.start)}  {hit.kind}: {shown!r}")
    return findings


def main(argv: list[str]) -> int:
    enable_unicode_output()
    parser = argparse.ArgumentParser(description="Scan tracked files for secrets and personal data.")
    parser.add_argument("repo", nargs="?", type=Path, default=Path("."))
    parser.add_argument("--public-repo", action="append", default=[], metavar="NAME",
                        help="a public repository whose <owner>/NAME is not a leak "
                             "(this repository's own name is always included)")
    parser.add_argument("--exclude", action="append", default=[], metavar="PATH",
                        help="a tracked path to skip, e.g. a file that documents the patterns")
    parser.add_argument("--online", action="store_true",
                        help="also scan for the GitHub organizations your gh login belongs to")
    parser.add_argument("--no-tailnet", action="store_true", help="skip tailnet names/addresses")
    parser.add_argument("--show-values", action="store_true",
                        help="print identity values instead of masking them (local use only)")
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    names = tracked_files(repo)
    if names is None:
        print(f"Not a git repository: {repo}", file=sys.stderr)
        return 2
    public = [*filter(None, [own_repository_name(repo)]), *args.public_repo]
    seeds = identity_seeds(tailnet=not args.no_tailnet, online=args.online, cwd=repo)
    findings = scan_files(repo, names, seeds, public, frozenset(args.exclude), args.show_values)
    print(f"Scanned {len(names)} tracked file(s) in {repo.name} "
          f"({sum(len(v) for v in seeds.values())} identity value(s) from this machine).")
    if not findings:
        print("Nothing found.")
        return 0
    print(f"{len(findings)} finding(s):")
    for line in findings:
        print(f"  {line}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
