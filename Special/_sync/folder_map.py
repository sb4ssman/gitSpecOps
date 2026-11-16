"""This machine's libraries as a folder map, each repository's state on its line.

The map shows only libraries, the folders that hold repositories (an organization's folder, or
any containing folder, at any depth) and the repositories themselves: no files, no other folders
(the user, 2026-11-15). Given --mapper PATH (Orbital-Workshop's generate_folder_structure.py), that
mapper's full map is drawn instead, files included, each repository's line with its state.
gitSpecOps does not depend on the mapper. Read-only: Git status only, nothing fetched or published.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from Basic import _cli
from Basic._console import enable_unicode_output
from Special._settings.fleet import load_fleet_settings
from Special._sync.advice import classify_repository, describe_repository
from Special._sync.observer import RootSpec, observe_roots

TREE_LINE = re.compile(r"^(?P<lead>(?:[│ ] {3}|    )*)(?:[├└]── )?(?:\S+ )?(?P<name>[^/]+)/?\s*$")


def library_roots(args) -> list[Path]:
    if args.root:
        return [Path(root).expanduser().resolve() for root in args.root]
    snapshot = load_fleet_settings(args.settings_home)
    app = snapshot.config("app") if snapshot is not None else None
    return [Path(root) for root in (app or {}).get("roots", [])]


def status_text(repo: dict) -> str:
    state, action = classify_repository(repo)
    return "clean" if state == "synced" else f"{describe_repository(repo)}: {action}"


def _mark(text: str) -> str:
    return f"{'✓' if text == 'clean' else '⚠'} {text}"


def built_in_map(root: Path, states: dict[Path, str]) -> list[str]:
    """The library, each folder on the way to a repository, and the repositories: nothing else."""
    tree: dict = {}
    for path in states:
        if path != root and root not in path.parents:
            continue
        node = tree
        for part in path.relative_to(root).parts:
            node = node.setdefault(part, {})

    def counts(node: dict, at: Path) -> tuple[int, int]:
        total = attention = 0
        for name, child in node.items():
            if at / name in states:
                total += 1
                attention += states[at / name] != "clean"
            inner = counts(child, at / name)
            total, attention = total + inner[0], attention + inner[1]
        return total, attention

    lines = [str(root) + (f"  {_mark(states[root])}" if root in states else "")]

    def draw(node: dict, at: Path, lead: str) -> None:
        names = sorted(node, key=str.casefold)
        for index, name in enumerate(names):
            last = index == len(names) - 1
            path = at / name
            if path in states:
                text = f"{name}  {_mark(states[path])}"
            else:
                total, attention = counts(node[name], path)
                need = f"{attention} need{'s' if attention == 1 else ''} something" if attention else "all clean"
                text = f"{name}/  ({total}, {need})"
            lines.append(f"{lead}{'└── ' if last else '├── '}{text}")
            draw(node[name], path, lead + ("    " if last else "│   "))

    draw(tree, root, "")
    return lines


def mapper_map(mapper: Path, root: Path, depth: int, states: dict[Path, str]) -> list[str] | None:
    """The mapper's full map of `root`, each repository's line with its state; None if it could not run."""
    try:
        done = subprocess.run([sys.executable, str(mapper), "--path", str(root), "--max-depth", str(depth)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    lines, stack, fenced = [], [], "```" not in done.stdout
    for raw in done.stdout.splitlines():
        if raw.strip().startswith("```"):  # the mapper writes Markdown; only its tree is drawn here
            fenced = not fenced
            continue
        if not fenced:
            continue
        match = TREE_LINE.match(raw) if ("──" in raw or raw.lstrip().startswith(("📁", "📄"))) else None
        if not match:
            lines.append(raw)
            continue
        level = len(match["lead"]) // 4 + (1 if "──" in raw else 0)
        stack = stack[:level] + [match["name"].strip()]
        path = root.joinpath(*stack[1:]) if len(stack) > 1 else root
        lines.append(f"{raw}  {_mark(states[path])}" if path in states else raw)
    return lines


def folder_map(args) -> int:
    screen = not _cli.machine(args)
    if screen:  # said at once, so it is clear the command is running before the library is read
        from Basic._station import banner
        banner("Machine map", "every library folder: its folders and repositories, and what each needs")
    roots = library_roots(args)
    if not roots:
        return _cli.fail(args, "machine map", "no library folders; pass --root, or add one with gitso machine add")

    def reading(done, total, _path):
        print(f"\r  Reading Git status: {done} of {total} repositories", end="" if done < total else "\n",
              flush=True)

    observation = observe_roots([RootSpec(root, True) for root in roots], None, progress=reading if screen else None)
    states = {Path(location): status_text(repo)
              for repo, location in zip(observation.repositories, observation.locations)}
    mapper = Path(args.mapper) if args.mapper else None
    maps, used = [], False
    for root in roots:
        drawn = mapper_map(mapper, root, args.depth, states) if mapper else None
        used = used or drawn is not None
        maps.append(drawn if drawn is not None else built_in_map(root, states))
    record = _cli.document("machine map", roots=[str(root) for root in roots], mapper=str(mapper) if used else None,
                           repositories=[{"path": str(path), "state": text} for path, text in sorted(states.items())],
                           warnings=list(observation.issues))

    def show():
        from Basic._station import line, say
        for lines in maps:
            say()
            for text in lines:
                print(f"  {text}")
        say()
        for issue in observation.issues:
            line(issue, "warning")
        attention = sum(text != "clean" for text in states.values())
        line(f"{len(states)} repositories, {attention} needing something. Nothing was fetched: ahead and "
             "behind are as of each repository's last fetch.", "muted")
        if mapper and not used:
            line(f"The mapper at {mapper} did not run; gitSpecOps drew the map.", "warning")
        elif used:
            line(f"Drawn with {mapper}, files included.", "muted")
    _cli.emit(args, record, show)
    return _cli.OK


def folder_map_main(argv=None) -> int:
    parser = _cli.parser("machine map", "This machine's libraries as a folder map, each repository's state on its line.")
    parser.add_argument("--settings-home", type=Path, help="selected user-data profile; nothing is created")
    parser.add_argument("--root", action="append", help="a folder to map (instead of the library folders)")
    parser.add_argument("--mapper", help="draw with this folder mapper (Orbital-Workshop's "
                        "generate_folder_structure.py) instead: everything, files included")
    parser.add_argument("--depth", type=int, default=3, help="the mapper's depth below each library (default 3)")
    enable_unicode_output()
    args = parser.parse_args(argv)
    try:
        return folder_map(args)
    except (OSError, ValueError) as exc:
        return _cli.fail(args, "machine map", str(exc))
