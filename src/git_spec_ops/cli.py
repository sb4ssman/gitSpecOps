"""Command-line dispatcher for gitSpecOps."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from . import __version__


def _run_module_main(module_name: str, argv: Sequence[str]) -> int:
    original_argv = sys.argv[:]
    sys.argv = [module_name, *argv]
    try:
        if module_name == "archive_updater":
            from . import archive_updater

            return archive_updater.main()
        if module_name == "archive_manager":
            from . import archive_manager

            return archive_manager.main()
        if module_name == "github_org_duplicator":
            from . import github_org_duplicator

            github_org_duplicator.main()
            return 0
    finally:
        sys.argv = original_argv
    raise ValueError(f"unknown module: {module_name}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="git-spec-ops",
        description="Cautious tools for multi-repository Git operations.",
    )
    parser.add_argument("--version", action="version", version=f"gitSpecOps {__version__}")

    subcommands = parser.add_subparsers(dest="command")

    archive = subcommands.add_parser("archive", help="Manage local folders of sibling Git repositories.")
    archive_subcommands = archive.add_subparsers(dest="archive_command")
    archive_subcommands.add_parser("update", help="Run the archive updater.")
    archive_subcommands.add_parser("manage", help="Install/list archive updater launchers.")

    github = subcommands.add_parser("github", help="Run GitHub-oriented repository operations.")
    github_subcommands = github.add_subparsers(dest="github_command")
    github_subcommands.add_parser("duplicate-org", help="Duplicate or download repositories with GitHub CLI.")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()

    if not argv:
        parser.print_help()
        return 0

    if argv[:2] == ["archive", "update"]:
        return _run_module_main("archive_updater", argv[2:])
    if argv[:2] in (["archive", "manage"], ["archive", "manager"]):
        return _run_module_main("archive_manager", argv[2:])
    if argv[:2] == ["github", "duplicate-org"]:
        return _run_module_main("github_org_duplicator", argv[2:])

    parser.parse_args(argv)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
