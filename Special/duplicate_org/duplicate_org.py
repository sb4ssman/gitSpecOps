"""Compatibility entry point. Use Special/duplicate_org.py for new callers.

Existing launchers keep working through the same implementation; no setup runs on import.
"""
from pathlib import Path
import sys

_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Special._org_duplicator.command import (
    non_repo_entries,
    choose_repo_subset,
    display_repo_table,
    check_prerequisites,
    setup_operation,
    validate_operation,
    show_summary,
    parse_args,
    main,
    cli_main,
    EFFECT,
)

if __name__ == "__main__":
    cli_main()
