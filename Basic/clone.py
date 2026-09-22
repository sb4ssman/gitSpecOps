"""Clone one repository into a destination that does not exist yet.

    python Basic/clone.py <url> <destination> [--mirror]

Never clones over anything: an existing destination is refused before git runs, so a clone can
only ever add a folder. Credentials are the user's own (`gh auth setup-git`, an SSH agent);
with prompts disabled, a missing one fails fast instead of waiting on an invisible question.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Basic._console import enable_unicode_output  # noqa: E402
from Basic._run import EXIT_CANNOT_START, Result, run  # noqa: E402

EFFECT = "local"

CLONE_TIMEOUT_SECONDS = 300


def clone(url: str, destination: Path | str, *, mirror: bool = False,
          timeout: float = CLONE_TIMEOUT_SECONDS) -> Result:
    """`git clone [--mirror] <url> <destination>`. Refuses an existing destination. Never raises."""
    destination = Path(destination)
    if destination.exists():
        return Result(["git", "clone", url, str(destination)], EXIT_CANNOT_START, "",
                      f"destination already exists: {destination}")
    args = ["git", "clone", *(["--mirror"] if mirror else []), url, str(destination)]
    return run(args, cwd=destination.parent if destination.parent.is_dir() else None,
               timeout=timeout)


def main(argv: list[str]) -> int:
    enable_unicode_output()
    parser = argparse.ArgumentParser(description="Clone one repository (never over anything).")
    parser.add_argument("url")
    parser.add_argument("destination", type=Path)
    parser.add_argument("--mirror", action="store_true", help="bare mirror of every ref")
    args = parser.parse_args(argv)
    result = clone(args.url, args.destination, mirror=args.mirror)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
