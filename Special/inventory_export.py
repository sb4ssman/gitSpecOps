"""Record where every repository came from, so another machine can clone them.

Why:          another machine can only rebuild a library it has a record of.
Reads:        the repositories under the given roots and their remotes.
May change:   nothing.
Results:      the inventory in a JSON record, or in --out; a screen at a terminal.
Layer:        Special: this machine, once.
Status:       working

    gitso inventory export [--root [LABEL=]PATH ...] [--repo PATH ...] [--out FILE]
        [--max-depth N] [--hidden] [--no-prompt] [--answers FILE]

Where the repositories are:
  --root   a folder that contains repositories (repeat for several, on any drives). A bare path
           is labelled by its own folder name; `label=path` names it yourself.
  --repo   one repository that lives somewhere on its own (repeat as needed). These are kept
           together under the reserved label `loose`, each remembering where it was.
  Neither given, at a terminal: a folder dialog asks, and keeps asking "add another?" until done.

Where the record goes: stdout, as one JSON document, with progress and the summary on stderr, so
`inventory_export.py --root X > inventory.json` is a complete inventory. `--out FILE` writes it
there instead. A run with no folders named, at a terminal, is the guided path: it also asks where
to save. The record names every repository, private ones included, so it must never be committed:
`--out` is checked before scanning and refuses an existing file, a link, and a tracked or
unignored path inside a Git work tree. Nothing is written beside this source checkout by default.

Paths inside the record are relative to their label, never a drive letter, so each label can land
anywhere on restore. Per repository: every remote URL (credentials stripped), host/owner/name,
branch, head, last commit, flags for what a clone cannot bring back, and whatever the repository
says about itself (readme, project files, `.git/description`, URLs found in them) -- including
repositories with no remote. Observation only: git reads, no network, at most the one chosen file.
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
from Basic import _cli  # noqa: E402
from Basic._pick import can_ask, pick_directory, pick_save_file  # noqa: E402
from Special._inventory import LOOSE, build_roots, collect_inventory  # noqa: E402
from Special._security._private_files import private_path, write_private_json  # noqa: E402

EFFECT = "none"

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


def check_destination(out: Path) -> None:
    """Refuse a bad destination before the scan, not after it. The write repeats these checks."""
    if private_path(out).exists():
        raise ValueError(f"{out} already exists; an inventory never overwrites a file")


def main(argv: list[str]) -> int:
    enable_unicode_output()
    parser = _cli.parser("inventory export", "Record a library of repositories for cloning elsewhere (read-only).")
    parser.add_argument("--root", action="append", default=[], metavar="[LABEL=]PATH",
                        help="a folder containing repositories; repeat for several")
    parser.add_argument("--repo", action="append", default=[], metavar="PATH",
                        help="a single repository living on its own; repeat as needed")
    parser.add_argument("--out", type=Path, default=None,
                        help="write the inventory to this new file (otherwise it is in the printed record)")
    parser.add_argument("--max-depth", type=int, default=None, help="limit walk depth below each root")
    parser.add_argument("--hidden", action="store_true", help="also look inside hidden (dotted) folders")
    parser.add_argument("--no-prompt", action="store_true", help="never ask; use defaults or fail")
    parser.add_argument("--answers", type=Path, help="file of answers, one per prompt")
    args = parser.parse_args(argv)
    command = "inventory export"
    if args.answers:
        try:
            use_scripted_answers(args.answers.read_text(encoding="utf-8").splitlines(), strict=True)
        except OSError as exc:
            return _cli.fail(args, command, f"{exc}.")
    ask = can_ask() and not args.no_prompt
    root_specs, repo_specs = list(args.root), list(args.repo)
    out = args.out
    if not root_specs and not repo_specs:
        if not ask:
            return _cli.fail(args, command, "Give at least one --root or --repo (there is no terminal to ask).")
        root_specs = ask_for_folders()
        if not root_specs:
            return _cli.fail(args, command, "No folder chosen; nothing was done.", _cli.FAILED)
        if out is None:
            out = pick_save_file("Save the repository inventory as", initial_dir=Path.home(),
                                 initial_name=DEFAULT_NAME, default_ext=".json")
            if out is None:
                return _cli.fail(args, command, "No save location chosen; nothing was written.", _cli.FAILED)
    screen = not _cli.machine(args)
    try:
        if out is not None:
            check_destination(out)
        roots = build_roots(root_specs)
        for _label, path in roots:
            if not path.is_dir():
                raise ValueError(f"not a directory: {path}")
        if screen:
            from Basic._station import banner
            banner("Export inventory", str(out) if out else "printed below")
        inventory = collect_inventory(
            roots, loose=[Path(p) for p in repo_specs], max_depth=args.max_depth,
            include_hidden=args.hidden,
            progress=(lambda label, path: print(f"  [{label}] {path}", file=sys.stderr)) if screen else None)
        if out is not None:
            write_private_json(out, inventory)
    except (OSError, ValueError, RuntimeError) as exc:
        return _cli.fail(args, command, f"{exc}.")
    notes = [summarize(inventory)]
    if any(r["label"] == LOOSE for r in inventory["roots"]):
        notes.append(f"'{LOOSE}' = repositories that live on their own; restore asks where to put them.")
    notes.append("This record names every repository, private ones included. Do not commit it.")
    record = _cli.document(command, written=str(out) if out else None, notes=notes,
                           **({} if out else {"inventory": inventory}))

    def show():
        from Basic._station import line, notice, say
        say()
        if out is None:
            for text in json.dumps(inventory, indent=2, ensure_ascii=False).splitlines():
                print(text)
        for text in notes:
            line(text)
        notice("Written" if out else "Done", str(out) if out else "", "success")

    _cli.emit(args, record, show)
    return _cli.OK


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
