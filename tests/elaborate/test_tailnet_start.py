"""The tailnet tier keeps trying until Tailscale is up (2026-11-17).

After a reboot the app starts at sign-in, sometimes before Tailscale: it used to give up for
good, so the machine neither pulled its peers nor answered them. Pins: the first failure says so
once, retries are quiet, and a different Tailscale user stops the retries (retrying cannot help).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

import Elaborate._fleet.peer as peer  # noqa: E402


def network(lines):
    config = {"transports": {"tailnet": {"port": 0, "allowed_login": "me@example"}}, "fleet_secret": "33" * 32}
    return peer.PeerNetwork(config, own_report=lambda: None, store=None, log=lines.append)


class TailnetStartTests(unittest.TestCase):
    def test_not_up_yet_is_said_once_then_retried_quietly(self):
        lines = []
        tier = network(lines)
        with patch.object(peer, "local_identity", side_effect=OSError("Tailscale is not running")):
            self.assertFalse(tier.start())
            self.assertFalse(tier.start(quiet=True))
        self.assertEqual(len(lines), 1)
        self.assertIn("trying again", lines[0])
        self.assertFalse(tier.refused, "a Tailscale that is not up yet is worth retrying")

    def test_a_different_tailscale_user_stops_the_retries(self):
        lines = []
        tier = network(lines)
        with patch.object(peer, "local_identity", return_value={"login": "someone-else@example", "ip": "127.0.0.1"}):
            self.assertFalse(tier.start())
        self.assertTrue(tier.refused)


if __name__ == "__main__":
    unittest.main()
