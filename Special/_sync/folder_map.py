"""This machine's libraries as a folder map, each repository's state on its line.

gitSpecOps draws the map itself: library, then each folder, then every repository with what it
needs. When Orbital-Workshop's folder mapper is present (--mapper PATH, or found as
Orbital-Workshop/LLM_Tools/generate_folder_structure.py inside a library), its map is drawn instead
and each repository's line gets its state appended. gitSpecOps does not depend on the mapper.
Read-only: Git status only, nothing fetched, nothing published.
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

MAPPER = Path("Orbital-Workshop") / "LLM_Tools" / "generate_folder_structure.py"
TREE_LINE = re.compile(r"^(?P<lead>(?:[│ ] {3}|    )*)(?:[├└]── )?(?:\S+ )?(?P<name>[^/]+)/?\s*$")


def library_roots(args) -> list[Path]:
    if args.root:
        return [Path(root).expanduser().resolve() for root in args.root]
    snapshot = load_fleet_settings(args.settings_home)
    app = snapshot.config("app") if snapshot is not None else None
    return [Path(root) for root in (app or {}).get("roots", [])]


def find_mapper(roots: list[Path]) -> Path | None:
    """Orbital-Workshop's mapper inside a library, at most two folders down."""
    for root in roots:
        for candidate in (root / MAPPER, *(child / MAPPER for child in root.iterdir() if child.is_dir())):
            if candidate.is_file():
                return candidate
    return None


def status_text(repo: dict) -> str:
    state, action = classify_repository(repo)
    return "clean" if state == "synced" else f"{describe_repository(repo)}: {action}"


def built_in_map(root: Path, states: dict[Path, str]) -> list[str]:
    """Library, folder, repository: a tree of every repository under `root`."""
    folders: dict[str, list[tuple[str, str]]] = {}
    for path, text in states.items():
        if path != root and root not in path.parents:
            continue
        parts = path.relative_to(root).parts
        folder = parts[0] if len(parts) > 1 else ""
        folders.setdefault(folder, []).append(("/".join(parts[1:]) if folder else parts[0], text))
    lines = [f"{root}"]
    names = sorted(folders, key=str.casefold)
    for index, folder in enumerate(names):
        last_folder = index == len(names) - 1
        items = sorted(folders[folder], key=lambda item: item[0].casefold())
        if folder:
            attention = sum(text != "clean" for _name, text in items)
            lines.append(f"{'└── ' if last_folder else '├── '}{folder}/  ({len(items)}, "
                         + (f"{attention} need{'s' if attention == 1 else ''} something)" if attention else "all clean)"))
            lead = "    " if last_folder else "│   "
        else:
            lead = ""
        for position, (name, text) in enumerate(items):
            branch = "└── " if position == len(items) - 1 and (folder or last_folder) else "├── "
            lines.append(f"{lead}{branch}{name}  {'✓' if text == 'clean' else '⚠'} {text}")
    return lines


def mapper_map(mapper: Path, root: Path, depth: int, states: dict[Path, str]) -> list[str] | None:
    """The mapper's map of `root`, each repository's line with its state; None if it could not run."""
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
        name = match["name"].strip()
        stack = stack[:level] + [name]
        path = root.joinpath(*stack[1:]) if len(stack) > 1 else root
        lines.append(f"{raw}  {'✓' if states[path] == 'clean' else '⚠'} {states[path]}" if path in states else raw)
    return lines


def folder_map(args) -> int:
    roots = library_roots(args)
    if not roots:
        return _cli.fail(args, "machine map", "no library folders; pass --root, or add one with gitso machine add")
    observation = observe_roots([RootSpec(root, True) for root in roots], None)
    states = {Path(location): status_text(repo)
              for repo, location in zip(observation.repositories, observation.locations)}
    mapper = Path(args.mapper) if args.mapper else (None if args.no_mapper else find_mapper(roots))
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
        line(f"{len(states)} repositories. Nothing was fetched: ahead and behind are as of each repository's "
             "last fetch.", "muted")
        line(f"Drawn with {mapper}." if used else "Drawn by gitSpecOps. Orbital-Workshop's folder mapper is used "
             "when present (--mapper PATH).", "muted")
    _cli.emit(args, record, show)
    return _cli.OK


def folder_map_main(argv=None) -> int:
    parser = _cli.parser("machine map", "This machine's libraries as a folder map, each repository's state on its line.")
    parser.add_argument("--settings-home", type=Path, help="selected user-data profile; nothing is created")
    parser.add_argument("--root", action="append", help="a folder to map (instead of the library folders)")
    parser.add_argument("--mapper", help="path to Orbital-Workshop's generate_folder_structure.py")
    parser.add_argument("--no-mapper", action="store_true", help="draw with gitSpecOps even if the mapper is found")
    parser.add_argument("--depth", type=int, default=3, help="the mapper's depth below each library (default 3)")
    enable_unicode_output()
    args = parser.parse_args(argv)
    try:
        return folder_map(args)
    except (OSError, ValueError) as exc:
        return _cli.fail(args, "machine map", str(exc))
