"""Requests between machines and uncommitted-work summaries (the user, 2026-11-16): a request
reaches only the machine it names, from the machine that sent it; applying a fast-forward moves a
clean, behind copy; a change that is only line endings is said so. Temporary repositories only."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

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
        receipt = self.prime.published()
        other = {**receipt[0], "from": "other", "status": "done"}
        self.desk.receive([other], "other")
        self.assertNotIn("status", self.desk.outgoing()[0])
        self.desk.receive(receipt, "prime")
        self.assertEqual(self.desk.outgoing()[0]["status"], "waiting")
        self.prime.settle(sent["id"], "done", "alpha: pulled")
        self.prime.log("applied", self.prime.incoming()[0], "alpha: pulled")
        self.desk.receive(self.prime.published(), "prime")
        self.desk.receive(receipt, "prime")  # An older poll cannot move the request backwards.
        mine = self.desk.outgoing()[0]
        self.assertEqual((mine["status"], mine["result"]), ("done", "alpha: pulled"))
        self.assertIn('"event": "applied"', (self.root / "prime" / "tasks.log").read_text())

    def test_bad_requests_are_refused(self):
        with self.assertRaises(ValueError):
            self.desk.send("prime", "Prime", "delete", [{"repo_id": "a"}])
        with self.assertRaises(ValueError):
            self.desk.send("prime", "Prime", "pull", [])

    def test_remote_confirmation_binds_target_items_policy_and_one_execution(self):
        for mode in ("confirm", "typed"):
            with self.subTest(mode=mode):
                sent = self.desk.send("prime", "Prime", "clone", [{"owner": "team", "name": "tool", "library": "Work"}])
                request_id = sent["id"]
                self.prime.receive([sent], "desk", mode)
                receipt = next(item for item in self.prime.published() if item["answer_for"] == request_id)
                self.desk.receive([receipt], "prime")
                with self.assertRaises(ValueError):
                    self.prime.claim(request_id, mode)
                if mode == "typed":
                    with self.assertRaises(ValueError):
                        self.desk.confirm(request_id, "wrong")
                confirmed = self.desk.confirm(request_id, "team/tool" if mode == "typed" else "")
                changed = {**confirmed, "items": [{**confirmed["items"][0], "library": "Other"}]}
                self.assertEqual(self.prime.receive([changed], "desk", mode), 0)
                self.assertEqual(self.prime.receive([confirmed], "desk", "local"), 0)
                self.assertEqual(self.prime.receive([confirmed], "other", mode), 0)
                self.assertEqual(self.prime.receive([confirmed], "desk", mode), 1)
                with self.assertRaises(ValueError):
                    self.prime.claim(request_id, "automatic")
                self.assertEqual(self.prime.claim(request_id, mode)["items"][0]["library"], "Work")
                with self.assertRaises(ValueError):
                    self.prime.claim(request_id, mode)
                self.prime.settle(request_id, "done", "completed")
                self.prime.clear()
                self.assertEqual(self.prime.receive([confirmed], "desk", mode), 0)

    def test_interrupted_execution_is_reported_and_never_replayed(self):
        sent = self.desk.send("prime", "Prime", "pull", [{"repo_id": "r1"}])
        self.prime.receive([sent], "desk", "automatic")
        self.prime.claim(sent["id"], "automatic")
        self.prime.recover_interrupted()
        self.assertEqual(self.prime.incoming()[0]["status"], "partial")
        self.assertEqual(self.prime.receive([sent], "desk", "automatic"), 0)

    def test_legacy_peer_id_stays_bound_to_the_authenticated_device(self):
        self.assertTrue(self.desk.bind_peer("legacy-id", "ts-first"))
        restarted = RequestBook(self.root / "desk", "desk", "Desk")
        self.assertFalse(restarted.bind_peer("legacy-id", "ts-second"))
        self.assertTrue(restarted.bind_peer("legacy-id", "ts-first"))
        self.assertFalse(restarted.bind_peer("ts-first", "ts-second"))

    def test_expired_remote_confirmation_falls_back_to_local_approval(self):
        now = datetime.now(timezone.utc)
        with patch("Elaborate._fleet.requests._now", return_value=now):
            sent = self.desk.send("prime", "Prime", "pull", [{"repo_id": "r1"}])
            self.prime.receive([sent], "desk", "confirm")
            self.desk.receive(self.prime.published(), "prime")
            confirmed = self.desk.confirm(sent["id"], "")
        with patch("Elaborate._fleet.requests._now", return_value=now + timedelta(minutes=16)):
            self.assertEqual(self.prime.receive([confirmed], "desk", "confirm"), 0)
            with self.assertRaises(ValueError):
                self.prime.claim(sent["id"], "confirm")
            self.assertEqual(self.prime.claim(sent["id"], None)["status"], "running")


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
            self.assertIn("fast-forwarded", result)
            self.assertEqual((work / "a.txt").read_text(), "two\n")

    def test_only_the_copy_in_the_named_library_moves_and_the_end_is_honest(self):
        from Elaborate._fleet.requests import perform
        from Special._sync.manifest import library_name
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            origin, other = root / "origin.git", root / "other"
            first, second = root / "one" / "work", root / "two" / "work"
            git(root, "init", "-q", "--bare", "-b", "main", str(origin))
            git(root, "clone", "-q", str(origin), str(other))
            git(other, "config", "user.email", "t@example.invalid"); git(other, "config", "user.name", "t")
            (other / "a.txt").write_text("one\n")
            git(other, "add", "."); git(other, "commit", "-qm", "one"); git(other, "push", "-q", "origin", "HEAD:main")
            for copy in (first, second):
                copy.parent.mkdir()
                git(root, "clone", "-q", str(origin), str(copy))
            (other / "a.txt").write_text("two\n")
            git(other, "commit", "-qam", "two"); git(other, "push", "-q", "origin", "HEAD:main")
            libraries = [str(root / "one"), str(root / "two")]
            both = lambda repo_id: [first, second] if repo_id == "r1" else []
            item = {"repo_id": "r1", "name": "work", "library": library_name(root / "two")}
            status, text = perform({"kind": "pull", "items": [item]}, both, libraries)
            self.assertEqual((status, (second / "a.txt").read_text()), ("done", "two\n"))
            self.assertEqual((first / "a.txt").read_text(), "one\n", "the other library's copy was not touched")
            # A copy with uncommitted work is not moved; with one that is, the end is "partial".
            (first / "note.txt").write_text("mine\n")
            private = []
            status, text = perform({"kind": "pull", "items": [{"repo_id": "r1", "name": "work"},
                                                               {"repo_id": "gone", "name": "absent"}]},
                                   both, libraries, private=lambda name, detail: private.append(detail))
            self.assertEqual(status, "partial", text)
            self.assertIn("has uncommitted work", text)
            self.assertIn("absent: no copy here", text)
            self.assertNotIn(str(root), text, "no path reaches another machine")
            status, _ = perform({"kind": "pull", "items": [{"repo_id": "gone", "name": "absent"}]}, both, libraries)
            self.assertEqual(status, "failed")

    def test_a_clone_request_without_names_is_refused_in_words(self):
        result = run_request({"kind": "clone", "items": [{"repo_id": "r1", "name": "x"}]}, lambda _id: [], ["/nowhere"])
        self.assertIn("not known here", result)

    def test_a_clone_naming_a_folder_path_is_refused(self):
        item = {"host": "github.com", "owner": "o", "name": "x", "folder": "../outside"}
        result = run_request({"kind": "clone", "items": [item]}, lambda _id: [], ["/nowhere"])
        self.assertIn("not a plain folder name", result)

    def test_a_clone_naming_an_unknown_library_clones_nothing(self):
        item = {"host": "github.com", "owner": "o", "name": "x", "folder": "o", "library": "Elsewhere"}
        result = run_request({"kind": "clone", "items": [item]}, lambda _id: [], ["/nowhere/Github"])
        self.assertIn("no library called Elsewhere", result)


    def test_remote_operations_reject_unapproved_destinations_before_network_git(self):
        from Special._sync.actions import plan_catchup
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            repo = root / "example"
            git(root, "init", "-q", str(repo))
            git(repo, "remote", "add", "origin", "https://other.invalid/example/project.git")
            with patch("Special._sync.actions._fetch") as fetch:
                self.assertEqual(plan_catchup([repo], fleet=True)[0]["action"], "remote_policy")
                git(repo, "remote", "set-url", "origin", "https://github.com/example/project.git")
                from Special._sync.actions import _fleet_checkout_origin
                self.assertEqual(_fleet_checkout_origin(repo), "https://github.com/example/project.git")
                hook = repo / ".git" / "hooks" / "post-merge"
                hook.write_text("# test fixture, never executed\n", encoding="utf-8")
                self.assertEqual(plan_catchup([repo], fleet=True)[0]["action"], "remote_policy")
                hook.unlink()
                git(repo, "config", "url.https://other.invalid/.insteadOf", "https://github.com/")
                self.assertEqual(plan_catchup([repo], fleet=True)[0]["action"], "remote_policy")
                fetch.assert_not_called()
            for host, name in (("other.invalid", "project"), ("github.com", "CON.txt")):
                item = {"host": host, "owner": "example", "name": name}
                with patch("Special._sync.actions.apply_materialize") as clone:
                    result = run_request({"kind": "clone", "items": [item]}, lambda _id: [], [str(root)])
                    self.assertIn("requires local review", result)
                    clone.assert_not_called()
            self.assertIn("Invalid operation", run_request({"kind": "push", "items": [{"repo_id": "x"}]},
                                                            lambda _id: [], [str(root)]))


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
            (repo / "new folder").mkdir()
            for name in ("first.txt", "second.txt"):
                (repo / "new folder" / name).write_text("fresh")
            changes = working_changes(repo)
            by_name = {item["name"]: item for item in changes["files"]}
            self.assertTrue(by_name["notes.md"]["line_endings_only"])
            self.assertFalse(by_name["code.py"]["line_endings_only"])
            self.assertEqual(by_name["new.txt"]["status"], "untracked")
            self.assertEqual(by_name["new folder/"]["kind"], "folder")
            self.assertEqual((changes["untracked_files"], changes["untracked_folders"]), (1, 1))
            self.assertEqual(changes["summary"], "2 changed files, 1 new file, 1 new folder, 1 only line endings")
            self.assertNotIn("secret", str(changes))


if __name__ == "__main__":
    unittest.main()
