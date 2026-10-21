"""The one subprocess wrapper: bounded, never interactive, structured failures.

Offline: children are this Python interpreter, plus `git --version` and a git command in a
directory that is not a repository.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from Basic import _run  # noqa: E402
from Basic._run import (CommandFailed, CommandTimeout, run, run_checked,  # noqa: E402
                        run_git, stream)

FAILS: list[str] = []
PY = sys.executable


def check(label: str, ok: bool) -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {label}")
    if not ok:
        FAILS.append(label)


ok = run([PY, "-c", "print('héllo ✓')"], timeout=30)
check("ordinary run succeeds", ok.returncode == 0 and ok.stdout.strip() == "héllo ✓")
check("ordinary run is not flagged", not ok.timed_out and not ok.missing)

probe = "import os; print(os.environ.get('PYTHONUTF8'), os.environ.get('PYTHONIOENCODING'))"
for name in ("PYTHONUTF8", "PYTHONIOENCODING"):
    os.environ.pop(name, None)  # the caller said nothing, so the wrapper must supply it
seen = run([PY, "-c", probe], timeout=30)
check("children are told to speak UTF-8 (a Python child on Windows otherwise writes cp1252)",
      seen.stdout.split() == ["1", "utf-8"])
overridden = run([PY, "-c", probe], timeout=30, env={"PYTHONUTF8": "0", "PYTHONIOENCODING": "latin-1"})
check("a caller's own setting still wins", overridden.stdout.split() == ["0", "latin-1"])

missing = run(["gitspecops-no-such-binary"], timeout=5)
check("missing binary is a result, not a raise", missing.missing and missing.returncode == 127)

# On Windows the venv python.exe is a launcher running the real interpreter as its child.
# Killing only the launcher left the child holding the output pipe, so the "timed out" call
# still waited the full sleep -- a timeout that hung. It must return promptly.
started = time.monotonic()
slow = run([PY, "-c", "import time; time.sleep(60)"], timeout=0.5)
elapsed = time.monotonic() - started
check("timeout is a result, not a raise", slow.timed_out and slow.returncode == 124)
check(f"timeout returns promptly, tree killed ({elapsed:.1f}s < 20s)", elapsed < 20)

try:
    run_checked([PY, "-c", "import time; time.sleep(60)"], timeout=0.5)
    check("run_checked raises CommandTimeout", False)
except CommandTimeout:
    check("run_checked raises CommandTimeout", True)
check("CommandTimeout is a RuntimeError (retry loops catch it first)",
      issubclass(CommandTimeout, CommandFailed) and issubclass(CommandFailed, RuntimeError))
for argv, label in (([PY, "-c", "raise SystemExit(3)"], "nonzero exit"),
                    (["gitspecops-no-such-binary"], "missing binary")):
    try:
        run_checked(argv, timeout=30)
        check(f"run_checked raises CommandFailed on {label}", False)
    except CommandTimeout:
        check(f"run_checked raises CommandFailed on {label}", False)
    except CommandFailed:
        check(f"run_checked raises CommandFailed on {label}", True)

# stream(): the batch face. Big enough that writing stdin inline would fill both pipes.
ECHO = ("import sys\n"
        "for line in sys.stdin.buffer:\n"
        "    sys.stdout.buffer.write(line.upper())\n")
lines = [f"line {i:06d} {'x' * 80}\n".encode() for i in range(20000)]
with stream([PY, "-c", ECHO], timeout=120, feed=lines) as out:
    echoed = out.stdout.read().splitlines(keepends=True)
check("stream feeds and reads 2 MB both ways without deadlock",
      len(echoed) == len(lines) and echoed[-1] == lines[-1].upper())

started = time.monotonic()
try:
    with stream([PY, "-c", "import time; time.sleep(60)"], timeout=0.5) as out:
        out.stdout.read()
    check("stream raises CommandTimeout at its deadline", False)
except CommandTimeout:
    check("stream raises CommandTimeout at its deadline", True)
check(f"stream's timeout kills the tree promptly ({time.monotonic() - started:.1f}s < 20s)",
      time.monotonic() - started < 20)

try:
    with stream([PY, "-c", "print('partial'); raise SystemExit(3)"], timeout=30) as out:
        out.stdout.read()
    check("stream raises CommandFailed on a nonzero exit", False)
except CommandTimeout:
    check("stream raises CommandFailed on a nonzero exit", False)
except CommandFailed:
    check("stream raises CommandFailed on a nonzero exit", True)

try:
    with stream(["gitspecops-no-such-binary"], timeout=5) as out:
        pass
    check("stream raises CommandFailed for a missing binary", False)
except CommandFailed:
    check("stream raises CommandFailed for a missing binary", True)

# Bytes, not text: a text-mode stdout on Windows writes "y\r\n".
FOREVER = "import sys\nwhile True:\n    sys.stdout.buffer.write(b'y\\n'); sys.stdout.flush()\n"
started = time.monotonic()
with stream([PY, "-c", FOREVER], timeout=60) as out:
    first = out.stdout.readline()
    out.stop()
check("stop() ends an endless command early, without an error",
      first == b"y\n" and time.monotonic() - started < 20)


def first_line(argv):
    with stream(argv, timeout=60) as out:
        yield out._proc
        yield out.stdout.readline()


reader = first_line([PY, "-c", FOREVER])
child = next(reader)
next(reader)
reader.close()   # an abandoned generator leaves the block early
check("an abandoned stream's command is killed", child.poll() is not None)

env_probe = [PY, "-c", "import os; print(os.environ.get('GITSPECOPS_PROBE'))"]
check("caller env reaches the child", run(env_probe, timeout=30, env={"GITSPECOPS_PROBE": "x"}).stdout.strip() == "x")

check("git is recognized by name", _run._is_git(["git", "status"]))
check("git is recognized by full path", _run._is_git([r"C:\Program Files\Git\cmd\git.exe", "status"]))
check("gh is not git", not _run._is_git(["gh", "auth", "status"]))

if run(["git", "--version"], timeout=30).returncode == 0:
    with tempfile.TemporaryDirectory() as tmp:
        outside = run_git(Path(tmp), ["rev-parse", "--show-toplevel"])
        check("run_git outside a repo fails without raising", outside.returncode != 0)
    missing_dir = run_git(Path(tempfile.gettempdir()) / "gitspecops-no-such-dir", ["status"])
    check("run_git in a missing directory fails without raising", missing_dir.returncode != 0)
else:
    print("skip  git not installed")

if FAILS:
    print(f"\n{len(FAILS)} FAILED")
    raise SystemExit(1)
print("\nALL-RUN-TESTS-PASS")
