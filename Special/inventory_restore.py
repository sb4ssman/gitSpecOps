"""Clone the repositories in an inventory file onto this machine. Clone-only; never over anything.

    python Special/inventory_restore.py [INVENTORY] [--map LABEL=DEST ...] [--dest DIR]
        [--layout preserve|canonical] [--only LABEL ...] [--use-candidates]
        [--apply] [--yes] [--no-prompt] [--answers FILE]

The inventory: the path given, else a file dialog (or terminal prompt) asks for it.

Where things go. Each label in the file (a root, or `loose` for repositories that lived on their
own) needs a destination on THIS machine, any drive, any folder; it is created on apply:
  --map LABEL=DEST  that label goes there          --dest DIR  every label without a --map
  neither, at a terminal: a folder dialog asks for each label in turn, showing where it was.
Several destinations is the normal case: map each label separately. One tidy destination for a
haphazard library is `--dest DIR --layout canonical`, which files every repository at
<DIR>/<host>/<owner>/<name> whatever folder it came from; `preserve` (default) recreates the
recorded layout under each label's destination.

Without `--apply` this prints the plan and changes nothing. An existing destination is left
alone; a repository with no recorded remote is listed for a human (`--use-candidates` lets a
URL found in its readme or project files be used); what a clone cannot restore -- uncommitted
work, unpushed commits, stashes -- is named per row. Credentials are yours: this runs
`git clone` non-interactively with the `gh`/SSH access the machine already has.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Basic._confirm import confirm_typed, use_scripted_answers  # noqa: E402
from Basic._console import enable_unicode_output  # noqa: E402
from Basic._pick import can_ask, pick_directory, pick_open_file  # noqa: E402
from Basic.clone import clone  # noqa: E402
from Special._inventory import LOOSE, plan_restore, validate_inventory  # noqa: E402

EFFECT = "local"

DEFAULT_DIR = Path(_ROOT) / ".agents" / "output"


def render(rows: list[dict], *, applied: bool) -> str:
    lines = ["RESTORE RESULT" if applied else "RESTORE PLAN"]
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["action"]] = counts.get(row["action"], 0) + 1
        where = row.get("target") or f"{row['root']}/{row['path']}"
        lines.append(f"  [{row['action']:<12}] {row['root']}/{row['path']} -> {where}\n"
                     f"                 {row['detail']}")
    lines.append("")
    lines.append(", ".join(f"{n} {a}" for a, n in sorted(counts.items())) or "nothing to do")
    return "\n".join(lines)


def apply(rows: list[dict]) -> list[dict]:
    results = []
    for row in rows:
        if row["action"] != "clone":
            results.append(row)
            continue
        target = Path(row["target"])
        target.parent.mkdir(parents=True, exist_ok=True)
        done = clone(row["url"], target)
        if done.returncode:
            reason = " ".join((done.stderr or done.stdout or "git clone failed").split())[:240]
            results.append({**row, "action": "clone_failed", "detail": reason})
        else:
            results.append({**row, "action": "cloned", "detail": "cloned from " + row["url_source"]})
    return results


def parse_maps(specs: list[str]) -> dict[str, Path]:
    destinations: dict[str, Path] = {}
    for spec in specs:
        label, sep, raw = spec.partition("=")
        if not sep or not raw:
            raise ValueError(f"--map expects LABEL=DEST, got {spec!r}")
        destinations[label.strip().lower()] = Path(raw).expanduser().resolve()
    return destinations


def ask_destinations(roots: list[dict], destinations: dict[str, Path], only: set[str] | None) -> None:
    """Fill in a destination for every label still missing one, by asking."""
    for root in roots:
        label = root["label"]
        if label in destinations or (only and label not in only):
            continue
        was = root.get("source_path")
        where = pick_directory(f"Where should '{label}' go on this machine?"
                               + (f" (it was {was})" if was else " (repositories that lived on their own)"))
        if where is not None:
            destinations[label] = where.expanduser().resolve()


def main(argv: list[str]) -> int:
    enable_unicode_output()
    parser = argparse.ArgumentParser(description="Clone an inventory's repositories here (plan first).")
    parser.add_argument("inventory", type=Path, nargs="?", help="inventory file (asked for if omitted)")
    parser.add_argument("--map", action="append", default=[], metavar="LABEL=DEST",
                        help="destination for one label on this machine; repeat per label")
    parser.add_argument("--dest", type=Path, help="destination for every label without a --map")
    parser.add_argument("--layout", choices=("preserve", "canonical"), default="preserve")
    parser.add_argument("--only", action="append", metavar="LABEL", help="restore only these labels")
    parser.add_argument("--use-candidates", action="store_true",
                        help="for a repository with no remote, clone from a URL found in its own files")
    parser.add_argument("--apply", action="store_true", help="actually clone (otherwise: plan only)")
    parser.add_argument("--yes", action="store_true", help="with --apply, skip the typed confirmation")
    parser.add_argument("--no-prompt", action="store_true", help="never ask; use flags or fail")
    parser.add_argument("--answers", type=Path, help="file of answers, one per prompt")
    args = parser.parse_args(argv)
    if args.answers:
        try:
            use_scripted_answers(args.answers.read_text(encoding="utf-8").splitlines(), strict=True)
        except OSError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
    ask = can_ask() and not args.no_prompt
    path = args.inventory
    if path is None:
        if not ask:
            print("ERROR: give the inventory file (there is no terminal to ask).", file=sys.stderr)
            return 2
        path = pick_open_file("Choose the repository inventory to restore", initial_dir=DEFAULT_DIR,
                              filetypes=[("Inventory (JSON)", "*.json"), ("All files", "*.*")])
        if path is None:
            print("No inventory chosen; nothing was done.", file=sys.stderr)
            return 1
    only = {label.lower() for label in args.only} if args.only else None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        repos = validate_inventory(data)
        destinations = parse_maps(args.map)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    roots = data.get("roots", [])
    if args.dest:
        for root in roots:
            destinations.setdefault(root["label"], args.dest.expanduser().resolve())
    if ask:
        ask_destinations(roots, destinations, only)
    unmapped = [r["label"] for r in roots if r["label"] not in destinations and not (only and r["label"] not in only)]
    if unmapped:
        print(f"No destination for: {', '.join(unmapped)} (listed for review; use --map or --dest)", file=sys.stderr)
    if any(r["label"] == LOOSE for r in roots) and args.layout == "preserve":
        print("Note: 'loose' repositories lived in unrelated places; --layout canonical files them "
              "by host/owner/name instead.", file=sys.stderr)
    rows = plan_restore(repos, destinations, layout=args.layout, use_candidates=args.use_candidates,
                        selected_roots=only)
    print(render(rows, applied=False))
    to_clone = [r for r in rows if r["action"] == "clone"]
    if not args.apply:
        print("\nNothing was changed. Re-run with --apply to clone the rows marked 'clone'.")
        return 0
    if not to_clone:
        return 0
    if not args.yes and not confirm_typed("CLONE", f"\nType CLONE to clone {len(to_clone)} repositories: "):
        print("Declined; nothing was changed.")
        return 1
    results = apply(rows)
    print()
    print(render(results, applied=True))
    return 1 if any(r["action"] == "clone_failed" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
