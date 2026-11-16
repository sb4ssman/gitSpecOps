"""Protected values shared across the fleet (the user, 2026-11-16): added on one machine, added
on all; a removal, or a newly allowed value, is asked about; a "no" is not asked again; another
fleet's record changes nothing. Sealing for a synced folder when `cryptography` is installed.
Two temporary profiles stand in for two machines."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from Elaborate._fleet import sealed  # noqa: E402
from Elaborate._fleet.shared_policy import SharedPolicy, strengthens  # noqa: E402
from Special._security._policy_edit import LOOSEN_WORD, policy_change, policy_view  # noqa: E402

FLEET = "f" * 16
KEY = "ab" * 32


class Machine:
    def __init__(self, root: Path, name: str, fleet=FLEET):
        self.home = root / name
        self.home.mkdir()
        (self.home / "settings.json").write_text(json.dumps({"schema_version": 2}), encoding="utf-8")
        (self.home / "fleet").mkdir()
        self.shared = SharedPolicy(self.home, self.home / "fleet", fleet_id=fleet, machine_id=name, label=name)

    def lists(self):
        return policy_view(self.home)["lists"]

    def change(self, name, **change):
        policy_change(self.home, {"list": name, **change})


class SharedPolicyTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.desk, self.laptop = Machine(self.root, "desk"), Machine(self.root, "laptop")

    def test_the_rule_tightening_applies_loosening_asks(self):
        self.assertTrue(strengthens("add", "never_publish"))
        self.assertTrue(strengthens("remove", "safe_values"))
        self.assertFalse(strengthens("remove", "never_publish_words"))
        self.assertFalse(strengthens("add", "safe_values"))

    def test_a_value_added_on_one_machine_is_added_on_the_other(self):
        self.desk.change("never_publish", add=["Secret Name"])
        result = self.laptop.shared.receive(self.desk.shared.record())
        self.assertIn("Secret Name", self.laptop.lists()["never_publish"])
        self.assertTrue(result["applied"])
        self.assertNotIn("Secret Name", json.dumps(result), "what a merge says never holds a value")

    def test_a_removal_is_asked_about_and_a_yes_removes_it(self):
        for machine in (self.desk, self.laptop):
            machine.change("never_publish", add=["old-handle"])
            machine.shared.record()  # each has seen it
        self.desk.change("never_publish", remove=["old-handle"], confirm=LOOSEN_WORD)
        result = self.laptop.shared.receive(self.desk.shared.record())
        self.assertEqual(len(result["asked"]), 1)
        self.assertIn("old-handle", self.laptop.lists()["never_publish"], "nothing loosens without an answer")
        question = self.laptop.shared.questions()[0]
        self.assertEqual((question["kind"], question["from"]), ("remove", "desk"))
        self.laptop.shared.answer(question["id"], True)
        self.assertNotIn("old-handle", self.laptop.lists()["never_publish"])
        self.assertEqual(self.laptop.shared.questions(), [])

    def test_a_no_is_remembered(self):
        self.desk.change("safe_values", add=["example.invalid"], confirm=LOOSEN_WORD)
        self.laptop.shared.receive(self.desk.shared.record())
        question = self.laptop.shared.questions()[0]
        self.assertEqual(question["kind"], "add")
        self.laptop.shared.answer(question["id"], False)
        self.laptop.shared.receive(self.desk.shared.record())
        self.assertEqual(self.laptop.shared.questions(), [])
        self.assertNotIn("example.invalid", self.laptop.lists()["safe_values"])

    def test_a_value_removed_here_is_not_added_back_by_a_machine_that_still_has_it(self):
        for machine in (self.desk, self.laptop):
            machine.change("never_publish", add=["gone"])
            machine.shared.record()
        self.laptop.change("never_publish", remove=["gone"], confirm=LOOSEN_WORD)
        self.laptop.shared.receive(self.desk.shared.record())
        self.assertNotIn("gone", self.laptop.lists()["never_publish"])

    def test_another_fleets_record_changes_nothing(self):
        stranger = Machine(self.root, "stranger", fleet="0" * 16)
        stranger.change("never_publish", add=["theirs"])
        self.assertEqual(self.laptop.shared.receive(stranger.shared.record()), {"applied": [], "asked": []})
        self.assertNotIn("theirs", self.laptop.lists()["never_publish"])


class OverTheTailnetTests(unittest.TestCase):
    """The peer server hands the record to an authenticated peer, which merges it (PeerNetwork)."""

    def test_a_peer_pulls_the_record_and_merges_it(self):
        import threading
        from unittest.mock import patch

        import Elaborate._fleet.net as net
        from Elaborate._fleet.peer import PeerNetwork
        with tempfile.TemporaryDirectory() as folder:
            desk, laptop = Machine(Path(folder), "desk"), Machine(Path(folder), "laptop")
            desk.change("never_publish", add=["Secret Name"])
            server = net.make_peer_server(("127.0.0.1", 0), lambda: None, KEY, "me@example.invalid",
                                          authenticate=lambda ip: {"machine_id": "ts", "label": "laptop"},
                                          own_settings=desk.shared.record)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            network = PeerNetwork({"transports": {"tailnet": {"port": server.server_address[1]}}},
                                  lambda: None, store=None, log=lambda _text: None, shared=laptop.shared)
            with patch.object(net, "validate_server_url", lambda url: url):  # loopback stands in for the tailnet
                network.merge_settings({"ip": "127.0.0.1", "label": "desk"})
            self.assertIn("Secret Name", laptop.lists()["never_publish"])

    def test_an_unknown_device_gets_nothing(self):
        import threading
        import urllib.error
        import urllib.request

        import Elaborate._fleet.net as net

        def refuse(_ip):
            raise PermissionError("not this person's device")
        server = net.make_peer_server(("127.0.0.1", 0), lambda: None, KEY, "me@example.invalid",
                                      authenticate=refuse, own_settings=lambda: {"lists": {"never_publish": ["x"]}})
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with self.assertRaises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(f"http://127.0.0.1:{server.server_address[1]}/v1/settings", timeout=10)
        self.assertEqual(refused.exception.code, 403)
        refused.exception.close()


@unittest.skipUnless(sealed.available(), "the optional cryptography package is not installed")
class SealedTests(unittest.TestCase):
    def test_sealed_through_a_folder_and_opened_only_with_the_fleet_key(self):
        with tempfile.TemporaryDirectory() as folder:
            record = {"schema": 1, "lists": {"never_publish": ["Secret Name"]}}
            path = sealed.write_own(folder, record, KEY, "desk")
            self.assertNotIn(b"Secret Name", path.read_bytes())
            self.assertEqual(sealed.read_others(folder, KEY, "laptop"), [record])
            self.assertEqual(sealed.read_others(folder, "cd" * 32, "laptop"), [], "another fleet's key opens nothing")
            renamed = Path(folder) / "settings" / "other.sealed"
            renamed.write_bytes(path.read_bytes())
            with self.assertRaises(ValueError):
                sealed.open_sealed(renamed.read_bytes(), KEY, "other")


if __name__ == "__main__":
    unittest.main()
