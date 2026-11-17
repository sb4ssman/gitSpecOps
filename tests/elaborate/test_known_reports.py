"""A machine that is off still reaches a newcomer, through the peers that met it (2026-11-17).

The dual-boot box: its Windows side joined while its Linux side was off, so it never met it and
showed nothing, while every other machine kept Linux's last report. Peers now hand over the last
reports they hold (`/v1/known`). Pins: a machine not reachable now is learned that way; a machine
answering live is taken only from itself; an older relayed report never replaces a newer one.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

import Elaborate._fleet.net as net  # noqa: E402
import Elaborate._fleet.peer as peer  # noqa: E402
from Elaborate._fleet.store import FleetStore  # noqa: E402
from Special._sync.manifest import build_manifest, fleet_id_for  # noqa: E402

SECRET = "44" * 32
FLEET = fleet_id_for(SECRET)


def report(machine: str, minutes_ago: int) -> dict:
    stamp = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).replace(microsecond=0)
    manifest = build_manifest(FLEET, machine, machine, [], stamp.isoformat().replace("+00:00", "Z"))
    return {"manifest": manifest, "names": {}, "issues": []}


class KnownReportsTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = FleetStore(Path(folder.name) / "fleet.sqlite3", FLEET)
        config = {"machine_id": "box-win", "fleet_secret": SECRET,
                  "transports": {"tailnet": {"port": 8765, "allowed_login": "me@example"}}}
        self.network = peer.PeerNetwork(config, own_report=lambda: None, store=self.store, log=lambda *_: None)
        self.network.server = object()  # serving; the HTTP side is not under test here

    def poll(self, live: dict, known: list):
        hosts = [{"ip": f"100.0.0.{i}", "serving": True} for i, _ in enumerate(live, 1)]
        by_ip = {h["ip"]: r for h, r in zip(hosts, live.values())}
        with patch.object(net, "discover_hosts", return_value=hosts), \
                patch.object(peer, "fetch_peer_report", side_effect=lambda ip, port: by_ip[ip]), \
                patch.object(net, "fetch_known_reports", return_value=known), \
                patch.object(self.network, "merge_settings"), patch.object(self.network, "merge_name"), \
                patch.object(self.network, "merge_requests"):
            return self.network.poll()

    def stored(self):
        return {r["manifest"]["machine_id"]: r["manifest"]["observed_at"] for r in self.store.reports()}

    def test_a_machine_that_is_off_is_learned_from_a_peer_that_met_it(self):
        self.poll({"node": report("node", 1)}, known=[report("box-linux", 600)])
        self.assertIn("box-linux", self.stored())

    def test_a_live_machine_is_taken_only_from_itself(self):
        own = report("node", 1)
        self.poll({"node": own}, known=[report("node", 0)])  # a relayed copy of a live machine
        self.assertEqual(self.stored()["node"], own["manifest"]["observed_at"])

    def test_an_older_relayed_report_never_replaces_a_newer_one(self):
        newer = report("box-linux", 10)
        self.store.put("box-linux", newer)
        self.poll({"node": report("node", 1)}, known=[report("box-linux", 600)])
        self.assertEqual(self.stored()["box-linux"], newer["manifest"]["observed_at"])


if __name__ == "__main__":
    unittest.main()
