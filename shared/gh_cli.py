"""
gh_cli
======

SHARED SPECIAL OPERATION: one `gh` subprocess wrapper for the special operations that
talk to GitHub. No org logic, no policy — just: run `gh`, capture output, decode safely,
enforce timeouts. `gh` itself performs whatever the caller asks for; callers keep their
own confirmation rules before invoking anything that writes.

Shared rule: a method lives in `shared/` once two of the three special operations
(archive updater, org duplicator, sync suggester) need it. Stdlib only; no imports from
tool folders.

Standalone:

    python shared/gh_cli.py auth                    # read-only auth status check
"""

from __future__ import annotations

import subprocess
import sys

GH_TIMEOUT_SECONDS = 120


class GhError(RuntimeError):
    """Raised when gh is missing, times out, or (with check=True) exits nonzero."""


def run_gh(args: list[str], check: bool = True, capture: bool = True,
           timeout: int = GH_TIMEOUT_SECONDS) -> subprocess.CompletedProcess:
    """Run `gh` with args and return the CompletedProcess. Raises GhError on failure."""
    try:
        proc = subprocess.run(
            ["gh", *args],
            capture_output=capture,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        raise GhError("gh CLI not found; install from https://cli.github.com") from None
    except subprocess.TimeoutExpired:
        raise GhError(f"gh timed out after {timeout}s: gh {' '.join(args)}") from None
    if check and proc.returncode != 0:
        detail = (proc.stderr or "").strip() or "unknown error"
        raise GhError(f"gh {' '.join(args)} failed: {detail}")
    return proc


def gh_installed() -> bool:
    try:
        run_gh(["--version"])
        return True
    except GhError:
        return False


def gh_authenticated() -> bool:
    # `gh auth status` exits nonzero and reports on stderr when unauthenticated.
    return run_gh(["auth", "status"], check=False).returncode == 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 2
    if argv[0] == "auth":
        ok = gh_authenticated()
        print("✓ gh authenticated" if ok else "✗ gh not authenticated (run: gh auth login)")
        if not ok:
            proc = run_gh(["auth", "status"], check=False)
            detail = (proc.stderr or proc.stdout or "").strip()
            if detail:
                print(detail)
        return 0 if ok else 1
    print("usage: python shared/gh_cli.py auth", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
