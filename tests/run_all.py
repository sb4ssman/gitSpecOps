#!/usr/bin/env python3
"""Run every test file in this folder and report one summary.

Each test is a standalone script that exits non-zero on failure, so this runner stays as
dumb as the tests: run them all, never stop at the first failure, exit non-zero if any
failed. All tests here are offline and synthetic — none touch the network or a real repo.
"""

import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent


def main(argv: list[str]) -> int:
    files = sorted(path for path in TESTS_DIR.glob("test_*.py"))
    if not files:
        print("No test files found.")
        return 1
    results = []
    for path in files:
        print(f"=== {path.name} ===", flush=True)
        completed = subprocess.run([sys.executable, str(path)], cwd=TESTS_DIR.parent)
        results.append((path.name, completed.returncode))
        print(flush=True)
    failed = [name for name, code in results if code != 0]
    for name, code in results:
        print(f"{'PASS' if code == 0 else 'FAIL':4}  {name}")
    print(f"\n{len(results) - len(failed)}/{len(results)} test files passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
