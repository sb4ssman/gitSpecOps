"""Disposable-checkout coverage for the attended remote Resolve route."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from Elaborate._fleet.page_actions import PageActions  # noqa: E402
from Elaborate._fleet.requests import RequestBook  # noqa: E402

REPO = "a" * 32


class RemoteResolveTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="gitso-resolve-test-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.repo, self.remote = self.root / "checkout", self.root / "provider"
        self.home = self.root / "profile"
        self.home.mkdir()
        environment = patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
        environment.start()
        self.addCleanup(environment.stop)
        self.git(self.root, "init", "-q", "--bare", str(self.remote))
        self.git(self.root, "init", "-q", "-b", "main", str(self.repo))
        self.git(self.repo, "config", "user.name", "orbit-user")
        self.git(self.repo, "config", "user.email", "123+orbit-user@users.noreply.github.com")
        self.git(self.repo, "config", "commit.gpgsign", "false")
        (self.repo / "notes.txt").write_text("original\n", encoding="utf-8")
        self.git(self.repo, "add", "notes.txt")
        self.git(self.repo, "commit", "-qm", "Initial")
        self.git(self.repo, "remote", "add", "origin", self.remote.as_uri())
        self.git(self.repo, "push", "-qu", "origin", "main")
        self.sender = RequestBook(self.root / "sender", "ts-sender", "Sender")
        receiver = RequestBook(self.root / "receiver", "ts-receiver", "Receiver")
        self.host = PageActions({"roots": [str(self.root)]}, self.root, SimpleNamespace(
            local_checkouts=lambda repo_id: [self.repo] if repo_id == REPO else []),
            receiver, lambda: (self.home, None), None)
        self.host.request_mode = lambda: "automatic"

    @staticmethod
    def git(cwd, *arguments):
        return subprocess.run(["git", *arguments], cwd=cwd, check=True, capture_output=True, text=True).stdout

    def approve(self, op, expected="done", **fields):
        draft = {"op": op, **fields}
        request = self.sender.send("ts-receiver", "Receiver", "resolve", [{"repo_id": REPO}], resolve=draft)
        self.assertFalse(self.sender.published(device_id="ts-unrelated"))
        addressed = self.sender.published(device_id="ts-receiver")
        self.assertEqual(self.host.book.receive(addressed, "ts-sender", "automatic"), 1)
        with self.assertRaisesRegex(ValueError, "waiting for approval"):
            self.host.book.claim(request["id"], "automatic")
        settled = self.host.answer(request["id"])
        result = self.host.remote_resolve.result(request["id"], "ts-sender")
        self.assertEqual(settled["status"], expected, result)
        self.assertIsNone(self.host.remote_resolve.result(request["id"], "ts-unrelated"))
        self.assertFalse(self.host.book.published(device_id="ts-unrelated"))
        self.sender.receive(self.host.book.published(device_id="ts-sender"), "ts-receiver")
        receipt = self.sender.outgoing()[-1]
        self.assertEqual(receipt["status"], expected)
        self.assertNotIn("message", receipt["resolve"])
        return result

    def test_attended_diff_commit_and_checked_push(self):
        (self.repo / "notes.txt").write_text("updated\n", encoding="utf-8")
        (self.repo / "detail.txt").write_bytes(b"new detail\n")
        initial = self.git(self.repo, "rev-parse", "HEAD").strip()
        view = self.approve("changes")
        self.assertIn("+updated", view["unstaged"])
        checkout = view["checkout"]
        self.assertEqual(self.approve("untracked", checkout=checkout, file="detail.txt")["text"], "new detail\n")
        draft = {"checkout": checkout, "files": ["notes.txt", "detail.txt"], "message": "Update notes"}
        checked = self.approve("commit-plan", **draft)
        self.assertEqual(self.git(self.repo, "rev-parse", "HEAD").strip(), initial)
        rejected = self.approve("commit-apply", expected="failed",
                                **{**draft, "message": "Changed after review"}, plan_id=checked["plan_id"])
        self.assertFalse(rejected["ok"])
        checked = self.approve("commit-plan", **draft)
        committed = self.approve("commit-apply", **draft, plan_id=checked["plan_id"])
        self.assertTrue(committed["applied"])
        preview = self.approve("push-plan", checkout=checkout)
        self.assertEqual(preview["destination"], "refs/heads/main")
        self.assertEqual(preview["security"]["status"], "passed")
        self.assertEqual(self.git(self.remote, "rev-parse", "refs/heads/main").strip(), initial)
        pushed = self.approve("push-apply", checkout=checkout, plan_id=preview["plan_id"])
        self.assertTrue(pushed["applied"])
        self.assertEqual(self.git(self.remote, "rev-parse", "refs/heads/main"), self.git(self.repo, "rev-parse", "HEAD"))

    def test_checked_push_requires_the_provider_base_from_its_preview(self):
        (self.repo / "notes.txt").write_bytes(b"new change\n")
        self.git(self.repo, "add", "notes.txt")
        self.git(self.repo, "commit", "-qm", "Update notes")
        checkout = self.approve("changes")["checkout"]
        preview = self.approve("push-plan", checkout=checkout)
        self.git(self.repo, "push", "-q", "origin", "main")
        reply = self.approve("push-apply", expected="failed", checkout=checkout, plan_id=preview["plan_id"])
        self.assertEqual(reply["status"], "stale")
        self.assertFalse(reply["applied"])

    def test_attended_branch_fetch_and_stash_keep_untracked_files(self):
        branches = self.approve("branches")
        self.assertTrue(branches["branches"][0]["current"])
        self.assertEqual(branches["branches"][0]["upstream"], "origin/main")
        checkout = branches["checkout"]
        head = self.git(self.repo, "rev-parse", "HEAD")
        self.assertEqual(self.approve("fetch", checkout=checkout)["status"], "fetched")
        self.assertEqual(self.git(self.repo, "rev-parse", "HEAD"), head)
        self.assertEqual(self.approve("stashes", checkout=checkout)["stashes"], [])

        (self.repo / "notes.txt").write_bytes(b"tracked draft\n")
        (self.repo / "private-note.txt").write_bytes(b"untracked draft\n")
        draft = {"checkout": checkout, "message": "Pause notes work"}
        proposal = self.approve("stash-plan", **draft)
        self.assertEqual(proposal["files"], ["notes.txt"])
        self.assertEqual(proposal["untracked"], 1)
        (self.repo / "notes.txt").write_bytes(b"second draft\n")
        stale = self.approve("stash-apply", expected="failed", **draft, plan_id=proposal["plan_id"])
        self.assertEqual(stale["status"], "stale")
        proposal = self.approve("stash-plan", **draft)
        self.assertTrue(self.approve("stash-apply", **draft, plan_id=proposal["plan_id"])["applied"])
        self.assertEqual((self.repo / "notes.txt").read_text(encoding="utf-8").strip(), "original")
        self.assertTrue((self.repo / "private-note.txt").is_file())
        self.assertIn("Pause notes work", self.approve("stashes", checkout=checkout)["stashes"][0]["subject"])

    def test_path_outside_the_approved_checkout_is_refused(self):
        checkout = self.approve("changes")["checkout"]
        self.assertFalse(self.approve("untracked", expected="failed", checkout=checkout, file="../outside")["ok"])


if __name__ == "__main__":
    unittest.main()
