"""Run gitSpecOps' security scanner against this project's proposed commit.

Called by the local Git hooks before a commit is written. The index may be Git's
temporary index for a partial commit; preserve that environment. No scan report,
finding value, filename, commit message or raw subprocess error is printed.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Special._security._checks import inspect  # noqa: E402
from Special._security._checks._personal import RULES  # noqa: E402
from Special._security._material import scan  # noqa: E402
from Special._security._me import load_policy  # noqa: E402

TAILNET = RULES["tailnet address"]


def check(root: Path, message: Path | None = None) -> tuple[int, int]:
    """Return counts of held findings and coverage gaps, never private evidence."""
    policy = load_policy(root)
    original_allowed = policy.allowed

    def allowed(text, start, end):
        return not TAILNET.fullmatch(text[start:end]) and original_allowed(text, start, end)

    policy.allowed = allowed
    report = scan(root, policy, material="index")
    held = sum(item.check == "tailnet address" for item in report.findings)
    held += sum(item.check != "tailnet address" for item in report.actionable)
    if message is not None:
        with message.open("rb") as stream:
            raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            return held, len(report.gaps) + 1
        held += sum(item.classification != "quiet"
                    for item in inspect(raw.decode("utf-8"), "commit message", policy))
    return held, len(report.gaps)


def main(argv: list[str]) -> int:
    try:
        if len(argv) > 1:
            raise ValueError("unexpected arguments")
        held, gaps = check(ROOT, Path(argv[0]) if argv else None)
    except Exception:
        print("Commit blocked: the gitSpecOps security audit could not finish.", file=sys.stderr)
        return 1
    if held or gaps:
        print(f"Commit blocked by gitSpecOps: {held} finding(s), {gaps} coverage gap(s). "
              "Inspect the staged audit locally before retrying.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
