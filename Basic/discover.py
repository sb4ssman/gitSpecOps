"""Find Git repositories under a root. Read-only: a filesystem walk, no git, no network.

Why:          every larger operation starts by knowing which repositories exist.
Reads:        the folders under the root (no Git, no network).
May change:   nothing.
Results:      JSON without a terminal (or with --json); a screen at one.
Layer:        Basic: one Git or host operation.
Status:       working

    gitso discover <root> [--json] [--max-depth N] [--hidden]
        [--cross-filesystems] [--no-skip]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Basic._console import enable_unicode_output  # noqa: E402
from Basic import _cli  # noqa: E402
from Basic._discovery import find_repos  # noqa: E402

EFFECT = "none"


def _progress_throttle(interval: float = 2.0):
    """Progress callback printing to stderr at most every `interval` seconds."""
    state = {"last": 0.0}

    def show(scanned: int, found: int, current: str) -> None:
        now = time.monotonic()
        if now - state["last"] >= interval:
            state["last"] = now
            print(f"  scanned {scanned} dirs, found {found} repos — in {current}", file=sys.stderr)

    return show


def main(argv: list[str]) -> int:
    enable_unicode_output()
    parser = _cli.parser("discover", "Find Git repositories under a folder (read-only).")
    parser.add_argument("root", nargs="?", default=".", help="folder to look under (default: this one)")
    parser.add_argument("--max-depth", type=int, default=None, help="how many folder levels to look through")
    parser.add_argument("--hidden", action="store_true", help="also look inside hidden (dotted) folders")
    parser.add_argument("--cross-filesystems", action="store_true", help="follow other drives and mounts")
    parser.add_argument("--no-skip", action="store_true", help="also look inside folders usually skipped")
    args = parser.parse_args(argv)
    try:
        hits = find_repos(Path(args.root), max_depth=args.max_depth,
                          include_hidden=args.hidden, cross_filesystems=args.cross_filesystems,
                          skip_names=set() if args.no_skip else None,
                          progress=None if _cli.machine(args) else _progress_throttle())
    except NotADirectoryError as exc:
        return _cli.fail(args, "discover", f"Not a folder: {exc}")
    kinds: dict[str, int] = {}
    for hit in hits:
        kinds[hit.kind] = kinds.get(hit.kind, 0) + 1
    summary = ", ".join(f"{kind}: {count}" for kind, count in sorted(kinds.items())) or "none"
    return _cli.report(args, "discover", ok=True, page="Discover", context=(str(Path(args.root).resolve()),),
                       rows=[(f"[{hit.kind}]", hit.path) for hit in hits],
                       message=f"{len(hits)} repositories ({summary}).",
                       root=str(Path(args.root).resolve()), repos=[hit.__dict__ for hit in hits])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
