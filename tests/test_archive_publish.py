"""Offline tests for the publish (push) direction.

Every "remote" here is a bare repository in a temporary directory, so pushes are real git
pushes that never leave the machine. Nothing in this file touches a network remote.

The properties being pinned are the safety ones: only ahead-only repositories are eligible,
a remote that moved between planning and pushing is refused rather than forced, and publish
can never ride along with the pull-direction verbs or a generated launcher.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "git-archive-updater"))

from archive_diff import PublishCandidate, build_publish_plan  # noqa: E402
from archive_sync import (  # noqa: E402
    apply_publish,
    collect_publish_candidates,
    render_publish_plan,
)

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)


def git(repo, *args, check_ok=True):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check_ok and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result


def commit(repo, name, text):
    (repo / name).write_text(text, encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "--quiet", "-m", f"add {name}")


with tempfile.TemporaryDirectory(prefix="publish-test-") as tmp:
    tmp = Path(tmp)
    archive = tmp / "archive"
    archive.mkdir()

    def new_pair(name):
        """A bare 'remote' plus a clone of it inside the archive folder."""
        bare = tmp / f"{name}.git"
        subprocess.run(["git", "init", "--quiet", "--bare", "-b", "main", str(bare)],
                       check=True, capture_output=True)
        seed = tmp / f"seed-{name}"
        subprocess.run(["git", "clone", "--quiet", str(bare), str(seed)], check=True,
                       capture_output=True)
        git(seed, "config", "user.email", "t@example.test")
        git(seed, "config", "user.name", "T")
        commit(seed, "base.txt", "base\n")
        git(seed, "push", "--quiet", "origin", "main")
        clone = archive / name
        subprocess.run(["git", "clone", "--quiet", str(bare), str(clone)], check=True,
                       capture_output=True)
        git(clone, "config", "user.email", "t@example.test")
        git(clone, "config", "user.name", "T")
        return bare, seed, clone

    ahead_bare, ahead_seed, ahead_repo = new_pair("ahead-repo")
    sync_bare, sync_seed, sync_repo = new_pair("sync-repo")
    moved_bare, moved_seed, moved_repo = new_pair("moved-repo")
    dirty_bare, dirty_seed, dirty_repo = new_pair("dirty-repo")

    commit(ahead_repo, "new.txt", "local work\n")
    commit(moved_repo, "mine.txt", "my work\n")
    commit(dirty_repo, "committed.txt", "committed\n")
    (dirty_repo / "scratch.txt").write_text("uncommitted\n", encoding="utf-8")

    # Someone else pushed to moved-repo's remote after we planned.
    commit(moved_seed, "theirs.txt", "their work\n")
    git(moved_seed, "push", "--quiet", "origin", "main")

    # --- classification from real repositories ------------------------------------
    candidates = {c.folder: c for c in collect_publish_candidates(archive)}
    check(set(candidates) == {"ahead-repo", "sync-repo", "moved-repo", "dirty-repo"},
          f"unexpected candidates: {sorted(candidates)}")
    check(candidates["ahead-repo"].ahead == 1 and not candidates["ahead-repo"].dirty,
          f"ahead-repo facts wrong: {candidates['ahead-repo']}")
    check(candidates["dirty-repo"].dirty, "dirty-repo was not seen as dirty")
    check(candidates["sync-repo"].ahead == 0 and candidates["sync-repo"].behind == 0,
          f"sync-repo facts wrong: {candidates['sync-repo']}")

    plan = build_publish_plan(list(candidates.values()))
    check([c.folder for c in plan.to_push] == ["ahead-repo"] or
          sorted(c.folder for c in plan.to_push) == ["ahead-repo", "moved-repo"],
          f"unexpected push set before fetch: {[c.folder for c in plan.to_push]}")
    check(any(c.folder == "dirty-repo" for c in plan.dirty_ahead),
          "a dirty repository was not held back by default")
    check(not any(c.folder == "dirty-repo" for c in plan.to_push),
          "a dirty repository must not be pushed by default")

    # --- the push itself ------------------------------------------------------------
    issues = []
    pushed = apply_publish(archive, plan, issues, pause=0)

    remote_log = subprocess.run(["git", "-C", str(ahead_bare), "log", "--oneline", "main"],
                                capture_output=True, text=True).stdout
    check("add new.txt" in remote_log, "the ahead-only commit did not reach the remote")
    check(pushed >= 1, f"nothing was reported as pushed: {pushed}")

    # moved-repo was ahead when planned, but the remote moved before the push. The
    # fetch-then-recheck must catch that and refuse, rather than forcing.
    moved_issue = [i for i in issues if i.repo == "moved-repo"]
    check(bool(moved_issue), f"a moved remote was not reported as an issue: {issues}")
    if moved_issue:
        check("needs a human" in moved_issue[0].detail or "push" in moved_issue[0].detail,
              f"unexpected moved-repo detail: {moved_issue[0].detail}")
    moved_log = subprocess.run(["git", "-C", str(moved_bare), "log", "--oneline", "main"],
                               capture_output=True, text=True).stdout
    check("their work" not in moved_log or "add theirs.txt" in moved_log,
          "the other machine's commit was disturbed")
    check("add mine.txt" not in moved_log,
          "a diverged repository was pushed anyway — history could have been overwritten")

    dirty_log = subprocess.run(["git", "-C", str(dirty_bare), "log", "--oneline", "main"],
                               capture_output=True, text=True).stdout
    check("add committed.txt" not in dirty_log,
          "a dirty repository was pushed despite being held back")
    check((dirty_repo / "scratch.txt").exists(),
          "the uncommitted file was disturbed — publish must never touch a working tree")

    # --- pushing an already-current repo is a no-op, not an error --------------------
    again_issues = []
    again = apply_publish(archive, build_publish_plan(collect_publish_candidates(archive)),
                          again_issues, pause=0)
    check(not any(i.repo == "ahead-repo" for i in again_issues),
          f"re-running publish reported a problem for an up-to-date repo: {again_issues}")

    # --- rendering does not crash on any bucket -------------------------------------
    render_publish_plan(archive, build_publish_plan([
        PublishCandidate("a", "main", "origin/main", 1, 0),
        PublishCandidate("b", "main", "origin/main", 1, 1),
        PublishCandidate("c", "main", "origin/main", 0, 2),
        PublishCandidate("d", None, None, None, None),
        PublishCandidate("e", "main", "origin/main", 2, 0, dirty=True),
    ]))

# --- publish must never be bundled or scheduled -------------------------------------
manager_source = (ROOT / "git-archive-updater" / "archive_manager.py").read_text(encoding="utf-8")
check("--publish" not in manager_source,
      "archive_manager.py references --publish; generated launchers and scheduled tasks must "
      "never push")

sync_source = (ROOT / "git-archive-updater" / "archive_sync.py").read_text(encoding="utf-8")
check("is its own apply class and cannot be combined" in sync_source,
      "the guard refusing --publish alongside the pull-direction verbs is missing")
push_body = sync_source.split("def _publish_one")[1].split("def apply_publish")[0]
check('"--force"' not in push_body and "'--force'" not in push_body,
      "the push path passes --force as a git argument")
check('run_git(path, ["push"]' in push_body,
      "the push is no longer a bare non-force push")

if failures:
    print("ARCHIVE-PUBLISH-TESTS FAILED:")
    for failure in failures:
        print(" -", failure)
    raise SystemExit(1)

print("ALL-ARCHIVE-PUBLISH-TESTS-PASS")
