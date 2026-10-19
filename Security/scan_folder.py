"""Scan every repository under a folder's history at once; optionally plan each rewrite.

    python Security/scan_folder.py FOLDER [--depth N] [--online] [--no-tailnet]
                                          [--plan] [--keep VALUE] [--mine EMAIL]
                                          [--public-repo NAME]

For a set of repositories about to be published -- an organization's, a namespace's -- one
table instead of one report each. Every ref is scanned (`--all`: what a push would publish,
not only what the remote has), with the same rules as `scan_history.py`. Per repository: the
commits, the identities and values a rewrite would change, secrets, what text replacement
cannot reach (binary files, archives, photos with a GPS position), what could not be inspected,
and how many commit ids are quoted in the current files (they change in a rewrite; see
`rewrite_history.py relink`).

Each repository's full, unmasked report goes to its own git-ignored output folder, as
`scan_history.py` writes it. With `--plan`, a rewrite plan is also written for every
repository that needs one, and the single `apply` command for all of them is printed.
Planning reads; applying is still a separate, confirmed step. Read-only without `--plan`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Basic._console import enable_unicode_output  # noqa: E402
from Basic._discovery import find_repos  # noqa: E402
from Basic._run import run_git  # noqa: E402
from Security import _rewrite  # noqa: E402
from Security._history import scan_history  # noqa: E402
from Security._patterns import SECRETS  # noqa: E402
from Security._repo import patterns_for, tracked_files, write_report  # noqa: E402
from Security._seeds import identity_seeds  # noqa: E402
from Security._report import render  # noqa: E402

EFFECT = "local"  # reads; `--plan` writes plan folders and mirror clones, never a checkout

COLUMNS = ("commits", "identities", "values", "secrets", "unreachable", "located",
           "uninspected", "quoted ids")


def commits_of(repo: Path) -> list[str]:
    return run_git(repo, ["rev-list", "--all"]).stdout.split()


def quoted_ids(repo: Path, commits: list[str]) -> int:
    """Ids of `commits` (every repository scanned, since they quote each other) quoted in
    this repository's current tracked text files."""
    commits = sorted(commits)
    mapping = {sha: sha for sha in commits}
    total = 0
    for name in tracked_files(repo) or []:
        try:
            raw = (repo / name).read_bytes()
            if b"\0" in raw[:8192]:
                continue
            text = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        total += len(_rewrite.references(text, mapping, commits))
    return total


def summarize(report, plan: dict, quoted: int) -> dict:
    """One row of the table, from the scan and the plan it implies."""
    return {
        "commits": report.commits,
        "identities": len(plan["mailmap"]),
        "values": sum(1 for rule in plan["replacements"].values()
                      if rule["kind"] not in SECRETS),
        "secrets": len(plan["secrets"]),
        "unreachable": len(plan["unreachable"]),
        "located": len(plan["images_with_location"]),
        "uninspected": len(plan["not_inspected"]),
        "quoted ids": quoted,
        "needs rewrite": bool(plan["mailmap"] or plan["replacements"] or plan["remove_paths"]),
    }


def table(rows: dict[str, dict]) -> list[str]:
    width = max([len("repository"), *(len(name) for name in rows)])
    head = f"{'repository':<{width}}  " + "  ".join(f"{c:>{len(c)}}" for c in COLUMNS)
    lines = [head, "-" * len(head)]
    for name, row in rows.items():
        lines.append(f"{name:<{width}}  " + "  ".join(f"{row[c]:>{len(c)}}" for c in COLUMNS))
    return lines


def main(argv: list[str]) -> int:
    enable_unicode_output()
    parser = argparse.ArgumentParser(description="Scan every repository under a folder.")
    parser.add_argument("folder", type=Path)
    parser.add_argument("--depth", type=int, default=2, help="how deep to look (default 2)")
    parser.add_argument("--online", action="store_true",
                        help="also look for the GitHub organizations your gh login belongs to")
    parser.add_argument("--no-tailnet", action="store_true")
    parser.add_argument("--public-repo", action="append", default=[], metavar="NAME")
    parser.add_argument("--keep", action="append", default=[], metavar="VALUE",
                        help="a found value (or an image path) to leave alone, in every repo")
    parser.add_argument("--mine", action="append", default=[], metavar="EMAIL",
                        help="an address of yours to re-attribute, in every repo")
    parser.add_argument("--plan", action="store_true",
                        help="write a rewrite plan for every repository that needs one")
    args = parser.parse_args(argv)

    folder = args.folder.resolve()
    repos = [Path(hit.path) for hit in find_repos(folder, max_depth=args.depth)
             if hit.kind != "bare"]
    if not repos:
        print(f"No repositories under {folder}.", file=sys.stderr)
        return 2
    # Machine-wide seeds once (tailnet, organizations); each repo adds its own git identity.
    shared = identity_seeds(tailnet=not args.no_tailnet, online=args.online)
    every_commit = [sha for repo in repos for sha in commits_of(repo)]
    rows, plans, reports = {}, [], []
    for repo in repos:
        print(f"scanning {repo.name} ...", flush=True)
        seeds = {**shared, **{kind: values for kind, values in identity_seeds(
            tailnet=False, cwd=repo).items() if kind.startswith("your git")}}
        report = scan_history(repo, ["--all"], patterns_for(repo, seeds, args.public_repo))
        wider = _rewrite.widen_seeds(report, seeds, args.mine)
        if wider:   # an old address of yours is on the commits: search the contents too
            seeds = wider
            report = scan_history(repo, ["--all"], patterns_for(repo, seeds, args.public_repo))
        full, _ = render(report, show_values=True)
        reports.append(write_report(repo, "history", full))
        target = _rewrite._git_identity(repo)
        decided = _rewrite.build_plan(
            report, target=target, owner=_rewrite.repository_owner(repo),
            keep=args.keep, claim=args.mine,
            mine_emails=[*seeds.get("your git email", []), *args.mine],
            my_names=[*seeds.get("your git name", []), *seeds.get("your gh login", [])])
        rows[repo.name] = summarize(report, decided, quoted_ids(repo, every_commit))
        if args.plan and rows[repo.name]["needs rewrite"]:
            into = _rewrite.default_plan_dir(repo)
            _rewrite.plan(repo, into, seeds=seeds, keep=args.keep,
                                 public_repositories=args.public_repo, mine=args.mine,
                                 report=report)
            plans.append(into)
    print()
    print("\n".join(table(rows)))
    print("\nidentities/values: what a rewrite changes. unreachable: binary or archived files "
          "holding a value (only --remove-path fixes them). located: photos with a GPS "
          "position. quoted ids: commit ids in current files, which a rewrite makes stale.")
    print(f"\nFull reports (unmasked, git-ignored): {len(reports)} written, e.g. {reports[0]}")
    if any(row["secrets"] for row in rows.values()):
        print("!! Secrets were found: rotate them first. Read the full reports.")
    if plans:
        quoted = " ".join(f'"{path}"' for path in plans)
        print(f"\n{len(plans)} plan(s) written. Review each plan's summary.txt, then "
              "apply them all with one confirmation:")
        print(f"  python Security/rewrite_history.py apply {quoted}")
        print("After pushing and `follow`, fix quoted ids in each checkout with every plan:")
        print(f"  python Security/rewrite_history.py relink {quoted} --checkout <repo>")
    return 1 if any(row["needs rewrite"] or row["secrets"] for row in rows.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
