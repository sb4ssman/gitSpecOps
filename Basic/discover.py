"""Find Git repositories under a root. Read-only: a filesystem walk, no git, no network.

    python Basic/discover.py <root> [--json] [--max-depth N] [--hidden]
        [--cross-filesystems] [--no-skip]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Basic._console import enable_unicode_output  # noqa: E402
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
    parser = argparse.ArgumentParser(description="Find Git repositories under a root (read-only).")
    parser.add_argument("root", nargs="?", default=".", help="root to walk (default: cwd)")
    parser.add_argument("--json", action="store_true", help="emit a JSON manifest")
    parser.add_argument("--max-depth", type=int, default=None, help="limit walk depth")
    parser.add_argument("--hidden", action="store_true", help="also scan dotted directories")
    parser.add_argument("--cross-filesystems", action="store_true", help="follow other mounts")
    parser.add_argument("--no-skip", action="store_true", help="do not skip heavy/known dirs")
    args = parser.parse_args(argv)
    try:
        hits = find_repos(Path(args.root), max_depth=args.max_depth,
                          include_hidden=args.hidden, cross_filesystems=args.cross_filesystems,
                          skip_names=set() if args.no_skip else None,
                          progress=None if args.json else _progress_throttle())
    except NotADirectoryError as exc:
        print(f"Not a directory: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"root": str(Path(args.root).resolve()),
                          "repos": [h.__dict__ for h in hits]}, indent=2))
        return 0
    kinds: dict[str, int] = {}
    for hit in hits:
        kinds[hit.kind] = kinds.get(hit.kind, 0) + 1
        print(f"  [{hit.kind:<8}] {hit.path}")
    summary = ", ".join(f"{k}: {v}" for k, v in sorted(kinds.items())) or "none"
    print(f"\nTotal: {len(hits)} repos  ({summary})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
