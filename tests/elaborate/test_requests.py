"""Requests between machines and uncommitted-work summaries (the user, 2026-11-16): a request
reaches only the machine it names, from the machine that sent it; applying a fast-forward moves a
clean, behind copy; a change that is only line endings is said so. Temporary repositories only."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from Elaborate._fleet.requests import RequestBook, run_request  # noqa: E402
from Special._sync.changes import working_changes  # noqa: E402


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class RequestBookTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.desk = RequestBook(self.root / "desk", "desk", "Desk")
        self.prime = RequestBook(self.root / "prime", "prime", "Prime")

    def test_a_request_reaches_only_the_machine_it_names(self):
        sent = self.desk.send("prime", "Prime", "pull", [{"repo_id": "a" * 32, "name": "alpha"}])
        self.assertEqual(self.prime.receive(self.desk.outgoing(), "desk"), 1)
        self.assertEqual(self.prime.incoming()[0]["id"], sent["id"])
        other = RequestBook(self.root / "other", "other", "Other")
        self.assertEqual(other.receive(self.desk.outgoing(), "desk"), 0, "not addressed to it")
        self.assertEqual(self.prime.receive(self.desk.outgoing(), "someone-else"), 0, "not from who serves it")
        self.assertEqual(self.prime.receive(self.desk.outgoing(), "desk"), 0, "already here")

    def test_answered_requests_are_not_asked_again(self):
        self.desk.send("prime", "Prime", "pull", [{"repo_id": "a" * 32}])
        self.prime.receive(self.desk.outgoing(), "desk")
        request = self.prime.incoming()[0]
        self.prime.settle(request["id"], "dismissed", "no")
        self.prime.receive(self.desk.outgoing(), "desk")
        self.assertEqual([item["status"] for item in self.prime.incoming()], ["dismissed"])

    def test_the_asking_machine_learns_what_happened(self):
        sent = self.desk.send("prime", "Prime", "pull", [{"repo_id": "a" * 32, "name": "alpha"}])
        self.prime.receive(self.desk.published(), "desk")
        self.prime.settle(sent["id"], "done", "alpha: pulled")
        self.prime.log("applied", self.prime.incoming()[0], "alpha: pulled")
        self.desk.receive(self.prime.published(), "prime")
        mine = self.desk.outgoing()[0]
        self.assertEqual((mine["status"], mine["result"]), ("done", "alpha: pulled"))
        self.assertIn('"event": "applied"', (self.root / "prime" / "tasks.log").read_text())

    def test_bad_requests_are_refused(self):
        with self.assertRaises(ValueError):
            self.desk.send("prime", "Prime", "delete", [{"repo_id": "a"}])
        with self.assertRaises(ValueError):
            self.desk.send("prime", "Prime", "pull", [])


class ApplyTests(unittest.TestCase):
    def test_a_fast_forward_request_moves_a_clean_behind_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            origin, work, other = root / "origin.git", root / "work", root / "other"
            git(root, "init", "-q", "--bare", "-b", "main", str(origin))
            git(root, "clone", "-q", str(origin), str(other))
            for repo in (other,):
                git(repo, "config", "user.email", "t@example.invalid"); git(repo, "config", "user.name", "t")
            (other / "a.txt").write_text("one\n")
            git(other, "add", "."); git(other, "commit", "-qm", "one"); git(other, "push", "-q", "origin", "HEAD:main")
            git(root, "clone", "-q", str(origin), str(work))
            (other / "a.txt").write_text("two\n")
            git(other, "commit", "-qam", "two"); git(other, "push", "-q", "origin", "HEAD:main")
            request = {"kind": "pull", "items": [{"repo_id": "r1"}]}
            result = run_request(request, lambda repo_id: [work] if repo_id == "r1" else [], [str(root)])
            self.assertIn("pulled", result.lower())
            self.assertEqual((work / "a.txt").read_text(), "two\n")

    def test_a_clone_request_without_names_is_refused_in_words(self):
        result = run_request({"kind": "clone", "items": [{"repo_id": "r1", "name": "x"}]}, lambda _id: [], ["/nowhere"])
        self.assertIn("not known here", result)


class ChangesTests(unittest.TestCase):
    def test_line_endings_only_is_said_so_and_contents_never_appear(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder)
            git(repo, "init", "-q"); git(repo, "config", "core.autocrlf", "false")
            git(repo, "config", "user.email", "t@example.invalid"); git(repo, "config", "user.name", "t")
            (repo / "notes.md").write_bytes(b"secret line\nsecond\n")
            (repo / "code.py").write_bytes(b"x = 1\n")
            git(repo, "add", "."); git(repo, "commit", "-qm", "base")
            (repo / "notes.md").write_bytes(b"secret line\r\nsecond\r\n")
            (repo / "code.py").write_bytes(b"x = 2\n")
            (repo / "new.txt").write_text("fresh")
            changes = working_changes(repo)
            by_name = {item["name"]: item for item in changes["files"]}
            self.assertTrue(by_name["notes.md"]["line_endings_only"])
            self.assertFalse(by_name["code.py"]["line_endings_only"])
            self.assertEqual(by_name["new.txt"]["status"], "untracked")
            self.assertEqual(changes["summary"], "3 files changed, 1 only line endings, 1 new and not yet added")
            self.assertNotIn("secret", str(changes))


if __name__ == "__main__":
    unittest.main()
