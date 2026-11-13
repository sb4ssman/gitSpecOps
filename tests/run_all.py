#!/usr/bin/env python3
"""Run every test file in this folder and report one summary.

Each test is a standalone script that exits non-zero on failure, so this runner stays as
dumb as the tests: run them all, never stop at the first failure, exit non-zero if any
failed. All tests here are offline and synthetic — none touch the network or a real repo.

Several files run at once, each in its own Python process (they share no memory or
environment). A file's output is held and printed in one block when it finishes, so files
never interleave. `--jobs 1` runs them one at a time with output live, as before.

    python tests/run_all.py              # a quarter of the processors at once, at most 4
    python tests/run_all.py --jobs 8
    python tests/run_all.py --jobs 1     # one at a time, output as it happens
"""

import argparse
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
#: A quarter of the logical processors, at most 4. Measured on 16 cores (32 logical), 2026-11-13:
#: one at a time 371s; 4 at a time 108s; 8, 104s; 16, 103s. The floor is the slowest single file
#: (security/test_commit_gate.py, ~81s alone), so more than 4 only costs processor time.
DEFAULT_JOBS = max(1, min(4, (os.cpu_count() or 4) // 4))
SLOWEST_SHOWN = 8


def test_files() -> list[Path]:
    # Recursive: tests are grouped by area (archive/, duplicator/, sync/, fleet/, repo/).
    # Manual probes may launch real applications and must never join this offline suite,
    # even if a future probe author uses a test_ filename.
    return sorted((p for p in TESTS_DIR.rglob("test_*.py")
                   if "probes" not in p.relative_to(TESTS_DIR).parts),
                  key=lambda p: (p.parent.name, p.name))


def label(path: Path) -> str:
    return f"{path.parent.name}/{path.name}"


def run_live(path: Path) -> tuple[int, float]:
    started = time.perf_counter()
    print(f"=== {label(path)} ===", flush=True)
    code = subprocess.run([sys.executable, str(path)], cwd=TESTS_DIR.parent).returncode
    print(flush=True)
    return code, time.perf_counter() - started


def run_held(path: Path, printing: threading.Lock) -> tuple[int, float]:
    started = time.perf_counter()
    # Output is a pipe here, not the console: make the child write UTF-8 so a test that prints
    # a check mark cannot fail only because it ran in parallel.
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    done = subprocess.run([sys.executable, str(path)], cwd=TESTS_DIR.parent, env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                          text=True, encoding="utf-8", errors="replace")
    seconds = time.perf_counter() - started
    with printing:
        print(f"=== {label(path)} ({seconds:.1f}s) ===", flush=True)
        if done.stdout:
            print(done.stdout.rstrip(), flush=True)
        print(flush=True)
    return done.returncode, seconds


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run every test file and report one summary.")
    parser.add_argument("--jobs", "-j", type=int, default=DEFAULT_JOBS,
                        help=f"test files at once (default: a quarter of the processors, at most 4; here {DEFAULT_JOBS}); "
                             "1 runs them one at a time with live output")
    args = parser.parse_args(argv)
    # Piped (to a file, or `| tail`) Windows output is cp1252: a test's ⚠ must not stop the summary.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    if args.jobs < 1:
        parser.error("--jobs must be at least 1")
    files = test_files()
    if not files:
        print("No test files found.")
        return 1
    started = time.perf_counter()
    if args.jobs == 1:
        outcomes = [run_live(path) for path in files]
    else:
        printing = threading.Lock()
        print(f"Running {len(files)} test files, {args.jobs} at a time.\n", flush=True)
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            outcomes = list(pool.map(lambda path: run_held(path, printing), files))
    wall = time.perf_counter() - started
    results = [(label(path), code, seconds) for path, (code, seconds) in zip(files, outcomes)]
    failed = [name for name, code, _ in results if code != 0]
    for name, code, seconds in results:
        print(f"{'PASS' if code == 0 else 'FAIL':4}  {name}  ({seconds:.1f}s)")
    print(f"\nSlowest {SLOWEST_SHOWN}:")
    for name, _code, seconds in sorted(results, key=lambda r: -r[2])[:SLOWEST_SHOWN]:
        print(f"  {seconds:6.1f}s  {name}")
    total = sum(seconds for _, _, seconds in results)
    print(f"\n{len(results) - len(failed)}/{len(results)} test files passed in {wall:.1f}s "
          f"({total:.1f}s of test time, {args.jobs} at a time).")
    if failed:
        print("Failed: " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
