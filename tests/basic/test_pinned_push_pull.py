"""Push and pull do what was approved, whatever Git's configuration says (2026-11-17).

Pins (an outside review's first finding): a configured force refspec, a mirror remote or
`push.default` cannot widen or force `push`; it sends the checked-out commit to the branch it
tracks and nothing else. `fast_forward` refuses a branch that tracks another remote than the one
it was asked to use.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from Basic.pull import fast_forward  # noqa: E402
from Basic._facts import upstream_of  # noqa: E402
from Basic.push import push  # noqa: E402


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class PinnedTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.origin, self.work = self.root / "origin.git", self.root / "work"
        git(self.root, "init", "-q", "--bare", "-b", "main", str(self.origin))
        git(self.root, "clone", "-q", str(self.origin), str(self.work))
        for key, value in (("user.email", "t@example.invalid"), ("user.name", "t")):
            git(self.work, "config", key, value)
        self.commit("one")
        git(self.work, "push", "-q", "-u", "origin", "HEAD:main")

    def commit(self, text, repo=None):
        repo = repo or self.work
        (repo / "a.txt").write_text(text + "\n")
        git(repo, "add", ".")
        git(repo, "commit", "-qm", text)
        return git(repo, "rev-parse", "HEAD")

    def remote(self, ref="refs/heads/main"):
        return git(self.origin, "rev-parse", ref)

    def test_push_sends_this_commit_to_its_branch(self):
        self.assertEqual(upstream_of(self.work), ("origin", "refs/heads/main"))
        tip = self.commit("two")
        self.assertEqual(push(self.work).returncode, 0)
        self.assertEqual(self.remote(), tip)

    def test_a_force_refspec_and_a_mirror_remote_cannot_force_or_widen_it(self):
        # Another clone moves the remote on; this one makes a different commit: not a fast-forward.
        other = self.root / "other"
        git(self.root, "clone", "-q", str(self.origin), str(other))
        for key, value in (("user.email", "t@example.invalid"), ("user.name", "t")):
            git(other, "config", key, value)
        theirs = self.commit("theirs", other)
        git(other, "push", "-q", "origin", "HEAD:main")
        self.commit("mine")
        git(self.work, "branch", "side")
        git(self.work, "tag", "v1")
        git(self.work, "config", "remote.origin.push", "+refs/heads/*:refs/heads/*")
        git(self.work, "config", "push.default", "matching")
        git(self.work, "config", "push.followTags", "true")
        result = push(self.work)
        self.assertNotEqual(result.returncode, 0, "not a fast-forward, so Git refuses; nothing forces it")
        self.assertEqual(self.remote(), theirs, "the remote branch was not overwritten")
        refs = git(self.origin, "for-each-ref", "--format=%(refname)")
        self.assertNotIn("refs/heads/side", refs, "no other branch left this machine")
        self.assertNotIn("refs/tags/v1", refs, "no tag left this machine")
        git(self.work, "config", "remote.origin.mirror", "true")
        self.assertNotEqual(push(self.work).returncode, 0)
        self.assertEqual(self.remote(), theirs)

    def test_a_branch_without_an_upstream_pushes_nothing(self):
        git(self.work, "checkout", "-q", "-b", "local-only")
        self.commit("local")
        result = push(self.work)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("nothing was pushed", result.stderr)

    def test_pull_refuses_a_branch_that_tracks_another_remote(self):
        elsewhere = self.root / "elsewhere.git"
        git(self.root, "clone", "-q", "--bare", str(self.origin), str(elsewhere))
        git(self.work, "remote", "add", "elsewhere", str(elsewhere))
        git(self.work, "fetch", "-q", "elsewhere")
        git(self.work, "branch", "-q", "--set-upstream-to=elsewhere/main")
        answer = fast_forward(self.work, "origin")
        self.assertTrue(answer.startswith("failed:"), answer)
        self.assertIn("elsewhere", answer)
        git(self.work, "branch", "-q", "--set-upstream-to=origin/main")
        self.assertEqual(fast_forward(self.work, "origin"), "already current")


if __name__ == "__main__":
    unittest.main()
