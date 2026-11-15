"""Report one repository's facts. Read-only.

Why:          every judgment above starts from one repository's plain facts.
Reads:        one repository.
May change:   nothing.
Results:      JSON without a terminal (or with --json); a screen at one.
Layer:        Basic: one Git or host operation.
Status:       working

    gitso status <repo-path>
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Basic._console import enable_unicode_output  # noqa: E402
from Basic import _cli  # noqa: E402
from Basic._facts import repo_facts  # noqa: E402

EFFECT = "none"


def main(argv: list[str]) -> int:
    enable_unicode_output()
    parser = _cli.parser("status", "One repository's facts: branch, upstream, ahead, behind, changes. Read-only.")
    parser.add_argument("repo", type=Path)
    args = parser.parse_args(argv)
    args.repo = args.repo.resolve()
    if not args.repo.is_dir():
        return _cli.fail(args, "status", f"Not a folder: {args.repo}")
    facts = repo_facts(args.repo)
    return _cli.report(args, "status", ok=True, page="Status", context=(str(args.repo),),
                       rows=[(key.replace("_", " "), value) for key, value in facts.items()],
                       message="Read only; nothing was changed.", facts=facts)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
