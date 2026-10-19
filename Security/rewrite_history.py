"""Remove personal data from a repository's history: plan, apply in a mirror, verify -- then
move every clone onto the new history and fix the commit ids quoted in its files.

    python Security/rewrite_history.py plan   [REPO] [--as "Name <email>"] [--online]
                                               [--replace VALUE=REPLACEMENT] [--keep VALUE]
                                               [--remove-path PATH] [--mine EMAIL]
    python Security/rewrite_history.py apply  PLAN_DIR [PLAN_DIR ...] [--yes]
    python Security/rewrite_history.py verify PLAN_DIR [PLAN_DIR ...]
    python Security/rewrite_history.py follow [REPO] [--yes]
    python Security/rewrite_history.py relink PLAN_DIR [PLAN_DIR ...] [--checkout PATH]
                                               [--write]

**plan** scans everything the repository's history holds (see `scan_history.py`) and writes,
into a private folder git never publishes (this checkout's ignored `.agents/output/security/`):

- `mailmap.txt` -- every published author/committer identity that is personal data, mapped to
  one public identity (default: this repository's configured `user.name` / `user.email`, which
  should be your GitHub noreply address);
- `replacements.txt` -- every personal value found in files, file names and commit messages,
  mapped to a placeholder (`<tailnet-ip>`, `machine-a`, `<library-root>`, ...). Word-bounded
  regular expressions, so a value is replaced only where the scanner found it. **This file holds
  the real values, which is why it never lives in the repository.** Review it; add lines for
  what no scan can know (a private organization's name) with `--replace` or by hand;
- `expected.json` -- what verification checks: the values and addresses that must be gone, and
  every ref's commit count and tip tree before the rewrite;
- `mirror.git` -- a bare clone of the repository's branches and tags (remote-tracking refs are
  left out, so nothing can be confused with them). The rewrite happens there and only there.

A value text replacement cannot reach -- in a binary file, inside an archive, a photo's GPS
position -- is named at plan time; `--remove-path` drops such a file from all history.

The repository's own owner name is never rewritten: it is the public identity of the
repository (its clone URL), not a leak.

**apply** runs `git filter-repo` inside each `mirror.git` after one typed confirmation, then
verifies. It never touches the working checkout. `git filter-repo` must be installed
(https://github.com/newren/git-filter-repo).

**verify** proves the mirror is clean (no planned value, no old identity) and that nothing else
changed: same commit count on every ref, and an identical tip tree wherever the current files
held no planned value. Then it prints the push steps. **Pushing is yours.** It replaces
published history (a forced push, which gitSpecOps never performs itself).

**follow** moves a clone made before the rewrite -- on any machine -- onto the new history: it
fetches, refuses if a tracked file is changed or any commit on the branch was never on the
remote (the remote-tracking reflogs record what the remote held), then runs `git reset --keep`.

**relink** rewrites commit ids quoted in a moved checkout's tracked files (work logs, notes) to
the new ids, from filter-repo's commit map, and leaves the edits for you to review and commit.
Give it every plan of a set rewritten together: repositories quote each other's commits ("shape
update to <id>"). filter-repo already does this for commit messages, within one repository.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Basic._confirm import confirm_typed  # noqa: E402
from Basic._console import enable_unicode_output  # noqa: E402
from Basic._run import run  # noqa: E402
from Security._rewrite import (REWRITE_TIMEOUT_SECONDS, _filename_callback,  # noqa: E402
                               _summary, default_plan_dir, follow, plan, push_steps, relink,
                               verify)
from Security._seeds import identity_seeds  # noqa: E402

# Writes a private plan folder and rewrites a mirror clone; `follow` moves a branch with
# `git reset --keep` and `relink` edits files, both in a checkout, both only when confirmed.
EFFECT = "local"

CONFIRMATION = "REWRITE"


def _apply(plan_dir: Path) -> int:
    """Run filter-repo in one plan's mirror. 0 when it ran; its exit status otherwise."""
    expected = json.loads((plan_dir / "expected.json").read_text(encoding="utf-8"))
    removal = [arg for glob in expected.get("remove_paths") or []
               for arg in ("--path-glob", glob)]
    rules = plan_dir / "replacements.txt"
    rewritten = run(["git", "filter-repo", "--force",
                     "--mailmap", str(plan_dir / "mailmap.txt"),
                     "--replace-text", str(rules),
                     "--replace-message", str(rules),
                     "--filename-callback", _filename_callback(rules),
                     *(removal + ["--invert-paths"] if removal else [])],
                    cwd=plan_dir / "mirror.git", timeout=REWRITE_TIMEOUT_SECONDS)
    sys.stdout.write(rewritten.stdout)
    sys.stderr.write(rewritten.stderr)
    if rewritten.returncode:
        print(f"git filter-repo failed in {plan_dir}; the mirror may be partly rewritten. Make "
              "a new plan.", file=sys.stderr)
    return rewritten.returncode


def main(argv: list[str]) -> int:
    enable_unicode_output()
    parser = argparse.ArgumentParser(description="Remove personal data from history.")
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("plan", help="scan and write the private plan and the mirror")
    p.add_argument("repo", nargs="?", type=Path, default=Path("."))
    p.add_argument("--into", type=Path, help="plan folder (default: the ignored output folder)")
    p.add_argument("--as", dest="identity", metavar="'Name <email>'",
                   help="the public identity to rewrite to (default: user.name/user.email)")
    p.add_argument("--replace", action="append", default=[], metavar="VALUE=REPLACEMENT")
    p.add_argument("--keep", action="append", default=[], metavar="VALUE",
                   help="a found value (or an image path) to leave alone")
    p.add_argument("--remove-path", action="append", default=[], metavar="PATH",
                   help="drop this path (or glob) from all history")
    p.add_argument("--public-repo", action="append", default=[], metavar="NAME")
    p.add_argument("--mine", action="append", default=[], metavar="EMAIL",
                   help="an address of yours (e.g. an old personal one) to re-attribute")
    p.add_argument("--online", action="store_true",
                   help="also look for the GitHub organizations your gh login belongs to")
    p.add_argument("--no-tailnet", action="store_true")
    a = sub.add_parser("apply", help="rewrite each plan's mirror with git filter-repo, verify")
    a.add_argument("plan_dirs", type=Path, nargs="+", metavar="PLAN_DIR")
    a.add_argument("--yes", action="store_true", help="skip the typed confirmation")
    v = sub.add_parser("verify", help="prove each mirror is clean; print the push steps")
    v.add_argument("plan_dirs", type=Path, nargs="+", metavar="PLAN_DIR")
    f = sub.add_parser("follow", help="move a clone made before the rewrite onto the new history")
    f.add_argument("repo", nargs="?", type=Path, default=Path("."))
    f.add_argument("--yes", action="store_true", help="move without asking")
    f.add_argument("--no-fetch", action="store_true", help="use the refs as last fetched")
    r = sub.add_parser("relink", help="update commit ids quoted in a moved checkout's files")
    r.add_argument("plan_dirs", type=Path, nargs="+", metavar="PLAN_DIR")
    r.add_argument("--checkout", type=Path,
                   help="the moved checkout (default: the repository the first plan was made "
                        "from)")
    r.add_argument("--write", action="store_true", help="make the edits (never commits)")
    args = parser.parse_args(argv)

    if args.action == "plan":
        repo = args.repo.resolve()
        target = None
        if args.identity:
            match = re.fullmatch(r"\s*(.+?)\s*<([^>]+)>\s*", args.identity)
            if not match:
                parser.error("--as must look like: Name <email>")
            target = (match.group(1), match.group(2))
        extra = {}
        for item in args.replace:
            value, sep, replacement = item.partition("=")
            if not sep or not value:
                parser.error("--replace must look like: VALUE=REPLACEMENT")
            extra[value] = replacement
        into = args.into or default_plan_dir(repo)
        seeds = identity_seeds(tailnet=not args.no_tailnet, online=args.online, cwd=repo)
        decided = plan(repo, into, seeds=seeds, target=target, keep=args.keep, extra=extra,
                       public_repositories=args.public_repo, mine=args.mine,
                       remove=args.remove_path)
        print("\n".join(_summary(decided, into.resolve())))
        return 0
    if args.action == "follow":
        return follow(args.repo, fetch=not args.no_fetch, assume_yes=args.yes)
    if args.action == "relink":
        plan_dirs = [path.resolve() for path in args.plan_dirs]
        expected = json.loads((plan_dirs[0] / "expected.json").read_text(encoding="utf-8"))
        checkout = (args.checkout or Path(expected["repository"])).resolve()
        try:
            lines, total = relink(plan_dirs, checkout, write=args.write)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 2
        if not total:
            print(f"No quoted commit ids from the old history in {checkout}.")
            return 0
        print(f"{total} quoted commit id(s) in {checkout} name the old history:")
        print("\n".join(lines))
        print("Edited. Review with `git diff`, then commit." if args.write
              else "Run again with --write to update them (nothing is committed).")
        return 0

    plan_dirs = [path.resolve() for path in args.plan_dirs]
    missing = [path for path in plan_dirs if not (path / "expected.json").is_file()
               or not (path / "mirror.git").is_dir()]
    if missing:
        print("Not a plan folder (expected.json and mirror.git): "
              + ", ".join(str(path) for path in missing), file=sys.stderr)
        return 2
    if args.action == "apply":
        print(f"This rewrites every commit in {len(plan_dirs)} mirror(s) (the mirrors only; "
              "your checkouts are not touched):")
        print("\n".join(f"  {path / 'mirror.git'}" for path in plan_dirs))
        if not args.yes and not confirm_typed(CONFIRMATION, f"Type {CONFIRMATION} to proceed: "):
            print("Nothing was rewritten.")
            return 1
    status = 0
    for plan_dir in plan_dirs:
        if args.action == "apply" and _apply(plan_dir):
            status = 1
            continue
        clean, lines = verify(plan_dir)
        print("\n".join(lines))
        if clean:
            print("\n".join(push_steps(plan_dir)))
        else:
            status = 1
    return status


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
