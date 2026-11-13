"""Following a rewritten history, ported from version 1: relink quoted ids, follow, sweep.

Pins: a quoted id maps only when it names exactly one old commit; relink never commits and
refuses a checkout still on the old history; follow refuses when anything could be lost
(uncommitted tracked changes, a commit the remote never held, no record of the old history)
and otherwise moves with `git reset --keep`; a sweep moves every stale clone under a folder.
Every value is invented; everything happens in temporary folders.
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from Basic._confirm import use_scripted_answers  # noqa: E402
from Basic._facts import shares_history  # noqa: E402
from Special._security import follow as rewrite  # noqa: E402

FAILS: list[str] = []
TARGET = ("Example Owner", "12345+example-owner@users.noreply.github.com")


def check(label: str, ok: bool, detail: object = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {label}")
    if not ok:
        FAILS.append(f"{label}: {detail}")


def git(repo: Path, *args: str, name="Example Owner", email="someone.real@example-mail.invalid"):
    env = {**os.environ, "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email,
           "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email}
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=env)
    if done.returncode:
        raise RuntimeError(f"git {args}: {done.stderr}")
    return done.stdout


def commit(repo: Path, message: str, **who) -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message, **who)


def rewrite_bare(bare: Path, work: Path, keep_first: bool = False) -> dict:
    """What filter-repo does, by hand: every commit again, same trees and times, new identity.
    `keep_first` keeps the root commit unchanged, as a real rewrite keeps every commit before its
    first change: the old and new histories then still share a commit."""
    git(work, "fetch", "-q", "origin")
    mapping, parent = {}, None
    commits = git(work, "rev-list", "--reverse", "origin/main").split()
    if keep_first:
        parent = mapping[commits[0]] = commits[0]
        commits = commits[1:]
    for sha in commits:
        fields = git(work, "log", "-1", "--format=%T%x00%aI%x00%cI%x00%B", sha).split("\0")
        env = {**os.environ, "GIT_AUTHOR_NAME": TARGET[0], "GIT_AUTHOR_EMAIL": TARGET[1],
               "GIT_COMMITTER_NAME": TARGET[0], "GIT_COMMITTER_EMAIL": TARGET[1],
               "GIT_AUTHOR_DATE": fields[1], "GIT_COMMITTER_DATE": fields[2]}
        args = ["git", "-C", str(work), "commit-tree", fields[0], "-m", fields[3].strip()]
        if parent:
            args[5:5] = ["-p", parent]
        parent = subprocess.run(args, capture_output=True, text=True, env=env,
                                check=True).stdout.strip()
        mapping[sha] = parent
    git(work, "push", "-q", "--force", "origin", f"{parent}:refs/heads/main")
    return mapping


def workspace_with(root: Path, mapping: dict) -> Path:
    """A rewrite workspace as clean_history leaves it: mirror.git/filter-repo/commit-map."""
    workspace = root / "workspace"
    (workspace / "mirror.git" / "filter-repo").mkdir(parents=True)
    (workspace / "mirror.git" / "filter-repo" / "commit-map").write_text(
        "old new\n" + "".join(f"{old} {new}\n" for old, new in mapping.items()), encoding="ascii")
    return workspace


# --- relink: commit ids quoted in files, from the commit map ----------------------------------
olds = {"a1b2c3d4" + "0" * 32: "f9e8d7c6" + "1" * 32, "a1b2ffff" + "0" * 32: "0badc0de" + "2" * 32}
found = rewrite.references("see a1b2c3d and a1b2 and a1b2c3d4000 and deadbee", olds)
check("a quoted id naming exactly one old commit is mapped, at its own length",
      [(old, new) for _offset, old, new in found] == [("a1b2c3d", "f9e8d7c"),
                                                      ("a1b2c3d4000", "f9e8d7c6111")], found)
with tempfile.TemporaryDirectory(prefix="follow-relink-") as temp:
    tmp = Path(temp)
    checkout = tmp / "proj"
    checkout.mkdir()
    git(checkout, "init", "-q", "-b", "main")
    (checkout / "LOG.md").write_text("fixed in a1b2c3d\n")
    commit(checkout, "log", email=TARGET[1], name=TARGET[0])
    workspace = workspace_with(tmp, olds)
    lines, total = rewrite.relink(workspace, checkout)
    check("relink lists the quoted ids and changes nothing without --write",
          total == 1 and "LOG.md:1" in lines[0]
          and (checkout / "LOG.md").read_text() == "fixed in a1b2c3d\n", lines)
    rewrite.relink([workspace], checkout, write=True)
    check("with write, the file holds the new id and nothing is committed",
          (checkout / "LOG.md").read_text() == "fixed in f9e8d7c\n"
          and git(checkout, "status", "--porcelain").strip() == "M LOG.md")
    head = git(checkout, "rev-parse", "HEAD").strip()
    (workspace / "mirror.git" / "filter-repo" / "commit-map").write_text(
        f"old new\n{head} {'3' * 40}\n", encoding="ascii")
    try:
        rewrite.relink(workspace, checkout)
        check("relink refuses a checkout still on the old history", False)
    except ValueError:
        check("relink refuses a checkout still on the old history", True)

# --- follow: a clone made before the rewrite --------------------------------------------------
# Every commit in one second: matching rewritten commits by their times once let `follow` take
# a never-pushed commit for a published one.
os.environ["GIT_AUTHOR_DATE"] = os.environ["GIT_COMMITTER_DATE"] = "2026-01-01T00:00:00+00:00"
with tempfile.TemporaryDirectory(prefix="follow-clones-") as temp:
    tmp = Path(temp)
    bare = tmp / "remote.git"
    git(tmp, "init", "-q", "--bare", "-b", "main", str(bare))
    seed = tmp / "seed"
    git(tmp, "clone", "-q", str(bare), str(seed))
    for step in range(3):
        (seed / "f.txt").write_text(f"step {step}\n")
        commit(seed, f"step {step}")
    git(seed, "push", "-q", "origin", "main")
    clean, ahead, dirty, unlogged = (tmp / name for name in ("clean", "ahead", "dirty", "unlogged"))
    for clone in (clean, ahead, dirty, unlogged):
        git(tmp, "clone", "-q", str(bare), str(clone))
    (ahead / "mine.txt").write_text("only here\n")
    commit(ahead, "work made only in this clone")
    git(clean, "branch", "-q", "old-side")
    rewrite_bare(bare, seed)
    for clone in (clean, ahead, dirty, unlogged):
        git(clone, "fetch", "-q", "origin")
    git(unlogged, "reflog", "expire", "--expire=now", "--all")
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        unproven = rewrite.follow(unlogged, fetch=False, assume_yes=True)
    check("with no record of what the remote held, follow refuses rather than guess",
          unproven == 1 and shares_history(unlogged) is False)
    (dirty / "f.txt").write_text("edited\n")
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        dirty_code = rewrite.follow(dirty, fetch=False, assume_yes=True)
        ahead_code = rewrite.follow(ahead, fetch=False, assume_yes=True)
    check("follow refuses a changed tracked file", dirty_code == 1
          and (dirty / "f.txt").read_text() == "edited\n")
    check("follow refuses when a commit exists only in this clone",
          ahead_code == 1 and (ahead / "mine.txt").is_file() and shares_history(ahead) is False)
    use_scripted_answers(["n"])
    with redirect_stdout(io.StringIO()):
        declined = rewrite.follow(clean, fetch=False)
    check("declining moves nothing", declined == 1 and shares_history(clean) is False)
    out = io.StringIO()
    with redirect_stdout(out):
        moved = rewrite.follow(clean, fetch=False, assume_yes=True)
    check("follow moves a clean clone onto the rewritten history",
          moved == 0 and shares_history(clean) is True
          and git(clean, "rev-parse", "HEAD") == git(clean, "rev-parse", "origin/main"), out.getvalue())
    check("and names a local branch still in the old history", "old-side" in out.getvalue())
    with redirect_stdout(io.StringIO()):
        again = rewrite.follow(clean, fetch=False, assume_yes=True)
    check("following again is a no-op", again == 0)

    # The observer says what happened instead of calling it divergence.
    from Special._sync.observer import observe_paths  # noqa: E402

    observation = observe_paths([ahead])
    check("suggest_sync names a rewritten upstream, without the path in the category",
          any(issue.startswith("upstream history was rewritten; review this clone before "
                               "moving it (do not pull or merge): ")
              for issue in observation.issues), observation.issues)

# --- sweep: one line on another machine moves every stale clone under a folder -----------------
with tempfile.TemporaryDirectory(prefix="follow-sweep-") as temp:
    tmp = Path(temp)
    bare = tmp / "remote.git"
    git(tmp, "init", "-q", "--bare", "-b", "main", str(bare))
    seed = tmp / "seed"
    git(tmp, "clone", "-q", str(bare), str(seed))
    (seed / "f.txt").write_text("one\n")
    commit(seed, "one")
    first = git(seed, "rev-parse", "HEAD").strip()
    (seed / "LOG.md").write_text(f"see {first[:7]}\n")
    commit(seed, "two")
    git(seed, "push", "-q", "origin", "main")
    work = tmp / "work"
    git(tmp, "clone", "-q", str(bare), str(work))
    mapping = rewrite_bare(bare, seed)
    workspace = workspace_with(tmp, mapping)
    with redirect_stdout(io.StringIO()):
        nothing = rewrite.follow_many([tmp], match=["no-such-remote"], assume_yes=True)
    check("a --match that names nothing changes nothing", nothing == 2)
    with redirect_stdout(io.StringIO()) as out:
        swept = rewrite.follow_many([tmp], match=["remote.git"], assume_yes=True)
    check("one sweep moves every stale clone under a folder and leaves current ones alone",
          shares_history(seed) is True and shares_history(work) is True
          and git(work, "rev-parse", "HEAD") == git(bare, "rev-parse", "main")
          and swept == 0 and "Moved 2; refused 0" in out.getvalue(), out.getvalue())
    _lines, total = rewrite.relink(workspace, work, write=True)
    check("after following, relink updates the quoted id and leaves it uncommitted",
          total == 1 and (work / "LOG.md").read_text() == f"see {mapping[first][:7]}\n"
          and git(work, "status", "--porcelain").strip() == "M LOG.md")

# --- a rewrite that kept the root: old and new histories still share a commit -----------------
# (2026-11-12) `follow` called such a clone "current" because the two shared *a* commit; a
# later pull would have merged the old history back in.
with tempfile.TemporaryDirectory(prefix="follow-shared-root-") as temp:
    tmp = Path(temp)
    bare = tmp / "remote.git"
    git(tmp, "init", "-q", "--bare", "-b", "main", str(bare))
    seed = tmp / "seed"
    git(tmp, "clone", "-q", str(bare), str(seed))
    for step in range(3):
        (seed / "f.txt").write_text(f"step {step}\n")
        commit(seed, f"step {step}")
    git(seed, "push", "-q", "origin", "main")
    stale = tmp / "stale"
    git(tmp, "clone", "-q", str(bare), str(stale))
    rewrite_bare(bare, seed, keep_first=True)
    git(stale, "fetch", "-q", "origin")
    check("the old clone still shares the kept root with the rewritten upstream",
          subprocess.run(["git", "-C", str(stale), "merge-base", "HEAD", "origin/main"],
                         capture_output=True).returncode == 0)
    from Special._sync.observer import observe_paths  # noqa: E402

    check("the observer calls it a rewritten upstream, not plain divergence",
          any(issue.startswith("upstream history was rewritten") for issue in observe_paths([stale]).issues))
    found = rewrite.assess(stale, fetch=False)
    check("a diverged clone that shares only the kept root is not 'current'", found["action"] == "move", found)
    with redirect_stdout(io.StringIO()):
        moved = rewrite.follow(stale, fetch=False, assume_yes=True)
    check("and follow moves it onto the rewritten history",
          moved == 0 and git(stale, "rev-parse", "HEAD") == git(stale, "rev-parse", "origin/main"))

os.environ.pop("GIT_AUTHOR_DATE")
os.environ.pop("GIT_COMMITTER_DATE")

if FAILS:
    print(f"\n{len(FAILS)} FAILED")
    for failure in FAILS:
        print(" -", failure)
    raise SystemExit(1)
print("\nALL-FOLLOW-REWRITE-TESTS-PASS")
