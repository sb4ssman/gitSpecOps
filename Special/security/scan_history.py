"""Read-only local reachable-history scan. No fetch or rewrite."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from Special.security._cli import main

EFFECT = "none"

if __name__ == "__main__":
    raise SystemExit(main("history"))
