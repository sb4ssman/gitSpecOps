"""Repository names per connection (the user, 2026-11-15): Tailscale carries them by default,
a synced folder and the state repository carry unnamed ids unless chosen. A fleet set up before
this keeps its one fleet-wide setting.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from Elaborate._fleet.config import shares_names  # noqa: E402
from Elaborate._fleet.peer import TransportPublisher  # noqa: E402
from Elaborate._transport.folder import FolderTransport  # noqa: E402
from Special._sync.manifest import build_manifest, fleet_id_for, names_anywhere, names_over, without_names  # noqa: E402

FLEET = fleet_id_for("33" * 32)
NAMED = {"repo_id": "a" * 32, "branch_id": "d" * 16, "has_upstream": True, "upstream_observed_at": None,
         "ahead": 0, "behind": 0, "staged": 0, "unstaged": 1, "untracked": 0, "stashes": 0,
         "operation": None, "name": {"host": "github.com", "owner": "example", "name": "shared"},
         "branch": "main", "head": "1" * 40}


def manifest(carries_names=True):
    return build_manifest(FLEET, "machine-a", "desk", [dict(NAMED)], carries_names=carries_names)


class NamesRuleTests(unittest.TestCase):
    def test_each_connection_has_its_own_choice(self):
        config = {"transports": {"tailnet": {"port": 8765, "names": True},
                                 "folder": {"path": "/x", "names": False},
                                 "repo": {"name": "you/state", "names": False}}}
        self.assertTrue(names_over(config, "tailnet"))
        self.assertFalse(names_over(config, "folder"))
        self.assertFalse(names_over(config, "repo"))
        self.assertTrue(names_anywhere(config))
        self.assertTrue(shares_names(config))

    def test_a_fleet_set_up_before_keeps_its_fleet_wide_setting(self):
        config = {"share_names": False, "transports": {"tailnet": {"port": 8765}, "folder": {"path": "/x"}}}
        self.assertFalse(names_over(config, "tailnet"))
        self.assertFalse(names_over(config, "folder"))
        self.assertFalse(names_anywhere(config))
        self.assertTrue(names_over({"transports": {"tailnet": {"port": 8765}}}, "tailnet"))

    def test_no_connection_carrying_names_means_none_are_built(self):
        config = {"transports": {"folder": {"path": "/x", "names": False}}}
        self.assertFalse(names_anywhere(config))


class WithoutNamesTests(unittest.TestCase):
    def test_names_branch_and_head_go_and_everything_else_stays(self):
        stripped = without_names(manifest())
        self.assertFalse(stripped["carries_names"])
        record = stripped["repositories"][0]
        for key in ("name", "branch", "head"):
            self.assertNotIn(key, record)
        self.assertEqual((record["repo_id"], record["unstaged"]), ("a" * 32, 1))

    def test_an_unnamed_manifest_is_left_as_it_is(self):
        unnamed = manifest(carries_names=False)
        self.assertIs(without_names(unnamed), unnamed)


class PublisherTests(unittest.TestCase):
    def test_a_folder_that_withholds_names_gets_unnamed_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            publisher = TransportPublisher({"folder": {"path": folder, "seconds": 300}}, clock=lambda: 0.0,
                                           names={"folder": False})
            self.assertEqual(publisher.publish(manifest(), changed=True, log=lambda _m: None), ["folder"])
            transport = FolderTransport(folder)
            written = transport.read_manifest(transport.list_manifests()[0])
        self.assertFalse(written["carries_names"])
        self.assertNotIn("name", written["repositories"][0])

    def test_a_folder_that_carries_names_gets_them(self):
        with tempfile.TemporaryDirectory() as folder:
            publisher = TransportPublisher({"folder": {"path": folder, "seconds": 300}}, clock=lambda: 0.0,
                                           names={"folder": True})
            publisher.publish(manifest(), changed=True, log=lambda _m: None)
            transport = FolderTransport(folder)
            written = transport.read_manifest(transport.list_manifests()[0])
        self.assertTrue(written["carries_names"])
        self.assertEqual(written["repositories"][0]["name"]["name"], "shared")


if __name__ == "__main__":
    unittest.main()
