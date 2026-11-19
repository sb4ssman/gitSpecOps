"""Show which Git gitso uses and how to update that installation.

Reads: the active Git executable, its version and hook command capabilities.
May change: nothing.
Results: the binary path, version, hook backend and platform update guidance.
Layer: Special: this machine, once.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from Basic import _cli  # noqa: E402
from Basic._run import run  # noqa: E402


def inspect_git():
    executable = shutil.which("git")
    if not executable:
        return None
    version = run([executable, "--version"], timeout=5)
    help_result = run([executable, "hook", "-h"], timeout=5)
    if version.returncode:
        return None
    named_hooks = "git hook list" in (help_result.stdout + help_result.stderr)
    resolved = Path(executable).resolve()
    if os.name == "nt":
        guidance = "Update the detected install through Git for Windows or its original package manager."
    elif sys.platform == "darwin":
        if "Cellar" in resolved.parts:
            guidance = "Use brew upgrade git."
        elif str(resolved).startswith("/opt/local/"):
            guidance = "Update the Git port with MacPorts."
        elif resolved == Path("/usr/bin/git"):
            guidance = "Update Apple's Xcode Command Line Tools through Software Update."
        else:
            guidance = "Update Git through the package manager or installer that provided this binary."
    else:
        guidance = "Use your distribution's package manager for system Git. For a separate install, use its original installer."
    return {"executable": str(resolved), "version": version.stdout.strip(),
            "named_hooks": named_hooks, "update_guidance": guidance}


def main(argv=None):
    command = "git-inspect"
    args = _cli.parser(command, __doc__.splitlines()[0]).parse_args(argv)
    result = inspect_git()
    if result is None:
        return _cli.fail(args, command, "Git could not be found or started.", _cli.FAILED)

    def screen():
        print(result["version"])
        print(result["executable"])
        print("Named hooks available." if result["named_hooks"] else "File-based hooks available.")
        print(result["update_guidance"])

    _cli.emit(args, _cli.document(command, True, **result), screen)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
