"""The page's actions, as their own unit (2026-11-17): routed to the right operation, with the
peer's profile, and a request that arrives is run and always ends in a state.

Pins: an unknown action is refused; a repository action is given the profile home; a request
sent to this machine runs here and says how it ended; an arriving request is run without Apply
unless `auto_requests` is off; one that cannot be run ends as "failed", never "running".
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from Elaborate._fleet.page_actions import PageActions  # noqa: E402
from Elaborate._fleet.requests import RequestBook  # noqa: E402


class Observer:
    paths = ()

    def local_checkouts(self, _repo_id):
        return ()


class PageActionTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.dir = Path(folder.name)
        self.config = {"machine_id": "desk", "label": "Desk", "roots": [str(self.dir)]}
        self.book = RequestBook(self.dir, "desk", "Desk")
        self.actions = PageActions(self.config, self.dir, Observer(), self.book,
                                   lambda: (self.dir / "profile", None), audits=None)

    def arrive(self):
        other = RequestBook(self.dir / "other", "lap", "Lap")
        sent = other.send("desk", "Desk", "pull", [{"repo_id": "r1", "name": "alpha"}])
        self.book.receive(other.published(), "lap", self.actions.request_mode())
        return sent

    def test_unknown_actions_are_refused(self):
        for action in ("rm", "security-nothing", "catchup-preview-all"):
            with self.assertRaises(ValueError, msg=action):
                self.actions.handle(action, {})

    def test_a_repository_action_gets_the_profile(self):
        with patch("Special._sync.resolve.repo_action", return_value={"not_counted": ["x"]}) as act:
            self.actions.handle("repo-action", {"op": "not-counted-list"})
        self.assertEqual(act.call_args.kwargs["home"], self.dir / "profile")
        self.assertEqual(self.config["not_counted"], ["x"], "the running observer sees the new list")

    def test_a_request_to_this_machine_runs_here_and_says_how_it_ended(self):
        answer = self.actions.handle("request-send", {"to": "desk", "kind": "pull",
                                                      "items": [{"repo_id": "r1", "name": "alpha"}]})
        self.assertEqual(answer["status"], "failed")
        self.assertIn("Not done here", answer["message"])
        self.assertTrue((self.dir / "fleet-rescan.request").exists())

    def test_an_arriving_request_runs_without_apply_and_ends_in_a_state(self):
        self.config["auto_requests"] = True
        sent = self.arrive()
        self.actions.run_waiting()
        ended = self.book.incoming()[0]
        self.assertEqual((ended["id"], ended["status"]), (sent["id"], "failed"))
        self.assertIn("alpha: no copy here", ended["result"])

    def test_auto_requests_waits_for_apply_by_default(self):
        self.arrive()
        self.actions.run_waiting()
        self.assertEqual(self.book.incoming()[0]["status"], "waiting")

    def test_pausing_blocks_an_already_queued_request(self):
        sent = self.arrive()
        self.config["auto_requests"] = "paused"
        with patch("Elaborate._fleet.requests.perform") as perform:
            self.actions.run_waiting()
            with self.assertRaisesRegex(ValueError, "paused"):
                self.actions.handle("request-answer", {"id": sent["id"], "accept": True})
            perform.assert_not_called()

    def test_a_request_that_cannot_be_run_is_failed_never_left_running(self):
        self.config["auto_requests"] = True
        self.arrive()
        with patch("Elaborate._fleet.requests.perform", side_effect=RuntimeError("boom")):
            self.actions.run_waiting()
        ended = self.book.incoming()[0]
        self.assertEqual(ended["status"], "failed")
        self.assertNotIn("boom", ended["result"], "the reason stays on this machine")

    def test_sender_approval_is_applied_once_under_receiver_policy(self):
        self.config["auto_requests"] = "typed"
        other = RequestBook(self.dir / "other", "lap", "Lap")
        sender = PageActions({"machine_id": "lap", "label": "Lap"}, self.dir, Observer(), other,
                             lambda: (self.dir / "profile", None), audits=None)
        sent = sender.handle("request-send", {"to": "desk", "to_label": "Desk", "kind": "clone",
                                               "items": [{"owner": "team", "name": "tool"}]})["sent"]
        self.book.receive(other.published(), "lap", self.actions.request_mode())
        other.receive(self.book.published(), "desk")
        with patch("Elaborate._fleet.requests.perform", return_value=("done", "cloned")) as perform:
            self.actions.run_waiting()
            perform.assert_not_called()
            sender.handle("request-confirm", {"id": sent["id"], "text": "team/tool"})
            self.book.receive(other.published(), "lap", self.actions.request_mode())
            self.actions.run_waiting()
            self.actions.run_waiting()
            perform.assert_called_once()
        other.receive(self.book.published(), "desk")
        self.assertEqual(other.outgoing()[0]["status"], "done")


if __name__ == "__main__":
    unittest.main()
