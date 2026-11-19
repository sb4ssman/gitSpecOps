"""Inspect or install fail-closed Git hooks on one local checkout.

Reads: Git's effective hooks directory and the selected gitso profile.
May change: after approval, local hook files and a scanner runtime in the profile.
Results: the effective hook path and mode. Scan checks normal commits. Local-only
         holds commits and pushes through Git's hooks while leaving stash available.
Layer: Special: this machine, once.

    gitso commit-gate /path/to/repo
    gitso commit-gate /path/to/repo --mode scan
    gitso commit-gate /path/to/repo --mode local-only
    gitso commit-gate /path/to/repo --mode off

Report existing hooks that need integration without replacing them. Changing the
checkout's mode takes effect without a network connection or app restart.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from Special._security._native_gate_cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
