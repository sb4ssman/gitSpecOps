"""Record where every repository came from, so another machine can clone them.

    python Special/inventory_export.py [--root [LABEL=]PATH ...] [--repo PATH ...] [--out FILE]
        [--max-depth N] [--hidden] [--no-prompt] [--answers FILE]

Where the repositories are:
  --root   a folder that contains repositories (repeat for several, on any drives). A bare path
           is labelled by its own folder name; `label=path` names it yourself.
  --repo   one repository that lives somewhere on its own (repeat as needed). These are kept
           together under the reserved label `loose`, each remembering where it was.
  Neither given, at a terminal: a folder dialog asks, and keeps asking "add another?" until done.

Where the file goes: `--out FILE`, else a save dialog (or a terminal prompt where no dialog is
possible). With no terminal at all (a script, a scheduled run) it writes the default file in the
gitignored `.agents/output/`; `--no-prompt` forces that. The file names every repository, private
ones included, so it must never be committed.

Paths inside the file are relative to their label, never a drive letter, so each label can land
anywhere on restore. Per repository: every remote URL (credentials stripped), host/owner/name,
branch, head, last commit, flags for what a clone cannot bring back, and whatever the repository
says about itself (readme, project files, `.git/description`, URLs found in them) -- including
repositories with no remote. Observation only: git reads, no network, one file written.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Basic._confirm import prompt_yes_no, use_scripted_answers  # noqa: E402
from Basic._console import enable_unicode_output  # noqa: E402
from Basic._files import atomic_write_bytes  # noqa: E402
from Basic._pick import can_ask, pick_directory, pick_save_file  # noqa: E402
from Special._inventory import LOOSE, build_roots, collect_inventory  # noqa: E402

EFFECT = "none"

DEFAULT_DIR = Path(_ROOT) / ".agents" / "output"
DEFAULT_NAME = "library_inventory.json"


def summarize(inventory: dict) -> str:
    repos = inventory["repositories"]
    with_remote = sum(1 for r in repos if r["remotes"])
    flag_counts: dict[str, int] = {}
    for repo in repos:
        for flag in repo["flags"]:
            flag_counts[flag] = flag_counts.get(flag, 0) + 1
    lines = [f"{len(repos)} repositories under {len(inventory['roots'])} label(s); {with_remote} with a "
             f"remote, {len(repos) - with_remote} without."]
    for flag, count in sorted(flag_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"  {flag}: {count}")
    return "\n".join(lines)


def ask_for_folders() -> list[str]:
    """Interactive: one folder at a time until the person has no more. [] if they cancel at once."""
    chosen: list[str] = []
    while True:
        folder = pick_directory("Choose a folder that contains repositories"
                                + (" (another)" if chosen else ""))
        if folder is None:
            break
        chosen.append(str(folder))
        if not prompt_yes_no("Add another folder?", default=False):
            break
    return chosen


def main(argv: list[str]) -> int:
    enable_unicode_output()
    parser = argparse.ArgumentParser(description="Record a library of repositories for cloning elsewhere (read-only).")
    parser.add_argument("--root", action="append", default=[], metavar="[LABEL=]PATH",
                        help="a folder containing repositories; repeat for several")
    parser.add_argument("--repo", action="append", default=[], metavar="PATH",
                        help="a single repository living on its own; repeat as needed")
    parser.add_argument("--out", type=Path, default=None, help="where to write the inventory")
    parser.add_argument("--max-depth", type=int, default=None, help="limit walk depth below each root")
    parser.add_argument("--hidden", action="store_true", help="also scan dotted directories")
    parser.add_argument("--no-prompt", action="store_true", help="never ask; use defaults or fail")
    parser.add_argument("--answers", type=Path, help="file of answers, one per prompt")
    args = parser.parse_args(argv)
    if args.answers:
        try:
            use_scripted_answers(args.answers.read_text(encoding="utf-8").splitlines(), strict=True)
        except OSError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
    ask = can_ask() and not args.no_prompt
    root_specs, repo_specs = list(args.root), list(args.repo)
    if not root_specs and not repo_specs:
        if not ask:
            print("ERROR: give at least one --root or --repo (there is no terminal to ask).", file=sys.stderr)
            return 2
        root_specs = ask_for_folders()
        if not root_specs:
            print("No folder chosen; nothing was done.", file=sys.stderr)
            return 1
    try:
        roots = build_roots(root_specs)
        for _label, path in roots:
            if not path.is_dir():
                raise ValueError(f"not a directory: {path}")
        inventory = collect_inventory(
            roots, loose=[Path(p) for p in repo_specs], max_depth=args.max_depth,
            include_hidden=args.hidden,
            progress=lambda label, path: print(f"  [{label}] {path}", file=sys.stderr))
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    out = args.out
    if out is None:
        out = (pick_save_file("Save the repository inventory as", initial_dir=DEFAULT_DIR,
                              initial_name=DEFAULT_NAME, default_ext=".json") if ask
               else DEFAULT_DIR / DEFAULT_NAME)
        if out is None:
            print("No save location chosen; nothing was written.", file=sys.stderr)
            return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(out, (json.dumps(inventory, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    print(summarize(inventory))
    if any(r["label"] == LOOSE for r in inventory["roots"]):
        print(f"  ('{LOOSE}' = repositories that live on their own; restore asks where to put them)")
    print(f"Wrote {out}")
    print("This file names every repository, private ones included. Do not commit it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
