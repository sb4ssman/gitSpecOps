"""Basic git commands against disposable local repositories. Offline: remotes are bare folders.

Pins the properties the layers above rely on: a clone never lands on an existing folder; a pull
only fast-forwards and reports a diverged branch as a failure instead of merging; a fetch moves
remote-tracking refs and not the branch; push has no way to force.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import ROOT, setup  # noqa: E402

setup()

from Basic.clone import clone  # noqa: E402
from Basic.fetch import fetch  # noqa: E402
from Basic.pull import ALREADY_CURRENT, UPDATED, fast_forward  # noqa: E402
from Basic.push import push  # noqa: E402
from Basic.reset_keep import ALREADY_THERE, MOVED, reset_keep  # noqa: E402

FAILS: list[str] = []


def check(label: str, ok: bool) -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {label}")
    if not ok:
        FAILS.append(label)


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if done.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {done.stderr}")
    return done.stdout.strip()


def commit(repo: Path, name: str) -> None:
    (repo / name).write_text(name, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", f"add {name}")


def identity(repo: Path) -> None:
    git(repo, "config", "user.email", "t@example.test")
    git(repo, "config", "user.name", "T")


with tempfile.TemporaryDirectory(prefix="basic-git-") as tmp:
    tmp = Path(tmp)
    bare = tmp / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    seed = tmp / "seed"
    check("clone into a new folder succeeds", clone(str(bare), seed).returncode == 0)
    identity(seed)
    commit(seed, "a.txt")
    git(seed, "push", "-q", "origin", "main")

    mine = tmp / "mine"
    check("second clone succeeds", clone(str(bare), mine).returncode == 0)
    identity(mine)
    refused = clone(str(bare), mine)
    check("clone refuses an existing destination", refused.returncode != 0
          and "already exists" in refused.stderr and (mine / "a.txt").exists())

    check("pull with nothing new is 'already current'", fast_forward(mine) == ALREADY_CURRENT)

    commit(seed, "b.txt")
    git(seed, "push", "-q", "origin", "main")
    before = git(mine, "rev-parse", "HEAD")
    check("fetch succeeds", fetch(mine, "origin").returncode == 0)
    check("fetch moves no local branch", git(mine, "rev-parse", "HEAD") == before)
    check("pull fast-forwards", fast_forward(mine) == UPDATED and (mine / "b.txt").exists())

    commit(seed, "c.txt")
    git(seed, "push", "-q", "origin", "main")
    commit(mine, "local.txt")
    head = git(mine, "rev-parse", "HEAD")
    diverged = fast_forward(mine)
    check("a diverged pull fails instead of merging",
          diverged.startswith("failed:") and git(mine, "rev-parse", "HEAD") == head)

    rejected = push(mine)
    check("a non-fast-forward push is refused by git", rejected.returncode != 0)
    check("the remote kept the other machine's commit",
          "add c.txt" in git(bare, "log", "--oneline", "main"))

    # reset_keep: `mine` holds local.txt; origin/main holds c.txt instead.
    git(mine, "fetch", "-q", "origin")
    upstream = git(mine, "rev-parse", "origin/main")
    (mine / "a.txt").write_text("edited", encoding="utf-8")   # a.txt is the same in both
    check("reset_keep moves the branch",
          reset_keep(mine, "origin/main") == MOVED and git(mine, "rev-parse", "HEAD") == upstream)
    check("reset_keep keeps an edit to a file the move does not touch",
          (mine / "a.txt").read_text(encoding="utf-8") == "edited")
    check("reset_keep onto where it already is reports so",
          reset_keep(mine, "origin/main") == ALREADY_THERE)
    git(mine, "checkout", "-q", "a.txt")
    (mine / "c.txt").write_text("my edit", encoding="utf-8")   # c.txt differs from `head`
    refused = reset_keep(mine, head)
    check("reset_keep refuses when the move would overwrite an edit",
          refused.startswith("failed:") and git(mine, "rev-parse", "HEAD") == upstream
          and (mine / "c.txt").read_text(encoding="utf-8") == "my edit")
    check("reset_keep refuses an unknown target",
          reset_keep(mine, "no-such-ref").startswith("failed:"))
    git(mine, "checkout", "-q", "c.txt")
    git(mine, "checkout", "-q", "--detach")
    check("reset_keep refuses a detached HEAD",
          reset_keep(mine, head).startswith("failed:") and git(mine, "rev-parse", "HEAD") == upstream)

# git translates its messages; the pull result must come from HEAD, not from English wording.
# This Windows git build ships no translations, so the translated output is played by a fake.
from Basic import pull as pull_module  # noqa: E402
from Basic._run import Result  # noqa: E402

_real_run_git = pull_module.run_git
for moved, label in ((False, "already current"), (True, "updated")):
    heads = iter(["a" * 40, ("b" if moved else "a") * 40])

    def translated(repo, args, **_kwargs):
        if args[:1] == ["rev-parse"]:
            return Result(args, 0, next(heads) + "\n", "")
        # A translated "Already up to date." on a no-op, and on a real update, alike.
        return Result(args, 0, "Bereits aktuell.\n", "")

    pull_module.run_git = translated
    try:
        check(f"a translated git still reports '{label}'", fast_forward("unused") == label)
    finally:
        pull_module.run_git = _real_run_git

push_code = (ROOT / "Basic" / "push.py").read_text(encoding="utf-8").split('"""', 2)[2]
check("Basic/push.py code has no force option", "force" not in push_code.lower())
reset_code = (ROOT / "Basic" / "reset_keep.py").read_text(encoding="utf-8").split('"""', 2)[2]
check("Basic/reset_keep.py code has no other reset mode",
      not any(mode in reset_code for mode in ("--hard", "--mixed", "--soft", "--merge")))

if FAILS:
    print(f"\n{len(FAILS)} FAILED")
    raise SystemExit(1)
print("\nALL-GIT-OPS-TESTS-PASS")
