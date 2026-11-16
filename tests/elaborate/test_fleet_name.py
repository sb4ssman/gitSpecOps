"""Fleets by name (the user, 2026-11-16: "couldn't it just be Home-Fleet on the tailnet?").
Machines answer with their fleet's name and id, never the key; joining by name gets the key from
a machine of that fleet; the newest name wins, and the placeholder never beats a real one."""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

import Elaborate._fleet.net as net  # noqa: E402
from Elaborate._fleet import setup_state  # noqa: E402
from Elaborate._fleet.peer import PeerNetwork  # noqa: E402
from Special._sync.manifest import fleet_id_for  # noqa: E402

KEY = "ab" * 32
NAMED = {"name": "Home-Fleet", "at": "2026-11-16T10:00:00+00:00"}


def serve(name=NAMED, key=KEY):
    server = net.make_peer_server(("127.0.0.1", 0), lambda: None, key, "me@example.invalid",
                                  authenticate=lambda ip: {"machine_id": "ts", "label": "desk"},
                                  own_name=lambda: name)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class FleetByNameTests(unittest.TestCase):
    def setUp(self):
        self.server = serve()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_address[1]
        host = {"label": "desk", "ip": "127.0.0.1", "serving": True, "url": f"http://127.0.0.1:{self.port}"}
        for patcher in (patch.object(net, "validate_server_url", lambda url: url),
                        patch.object(net, "discover_hosts", lambda **_kw: [host])):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_fleet_is_listed_by_name_and_never_shows_the_key(self):
        about = net.FleetClient(f"http://127.0.0.1:{self.port}").request("/v1/fleet")
        self.assertNotIn(KEY, json.dumps(about))
        fleets = setup_state.fleets_on_tailnet(port=self.port)
        self.assertEqual(fleets, [{"fleet_id": fleet_id_for(KEY), "name": "Home-Fleet", "machines": ["desk"]}])

    def test_joining_by_name_gets_the_key_and_the_name(self):
        self.assertEqual(setup_state.key_from_fleet(fleet_id_for(KEY), port=self.port), (KEY, NAMED))
        with self.assertRaisesRegex(ValueError, "no machine of that fleet"):
            setup_state.key_from_fleet("0" * 16, port=self.port)

    def test_a_newer_name_spreads_and_an_older_one_does_not(self):
        adopted = []
        config = {"fleet_secret": KEY, "fleet_name": {"name": "My fleet", "at": "1970-01-01T00:00:00+00:00"},
                  "transports": {"tailnet": {"port": self.port}}}
        network = PeerNetwork(config, lambda: None, store=None, log=lambda _t: None, adopt_name=adopted.append)
        network.merge_name({"ip": "127.0.0.1", "label": "desk"})
        self.assertEqual(adopted, [NAMED])
        self.assertEqual(config["fleet_name"]["name"], "Home-Fleet")
        config["fleet_name"] = {"name": "Renamed", "at": "2026-11-17T00:00:00+00:00"}
        network.merge_name({"ip": "127.0.0.1", "label": "desk"})
        self.assertEqual(len(adopted), 1, "an older name does not replace a newer one")

    def test_another_fleets_name_is_ignored(self):
        adopted = []
        config = {"fleet_secret": "cd" * 32, "transports": {"tailnet": {"port": self.port}}}
        PeerNetwork(config, lambda: None, store=None, log=lambda _t: None,
                    adopt_name=adopted.append).merge_name({"ip": "127.0.0.1", "label": "desk"})
        self.assertEqual(adopted, [])


class NamingTests(unittest.TestCase):
    def test_a_name_is_tidied_and_checked(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch("Elaborate._fleet.cli.load_saved", return_value={}), \
                patch("Elaborate._fleet.cli.save_saved") as saved:
            named = setup_state.name_fleet(Path(folder), Path(folder), name="  Home   Fleet ")
            self.assertEqual(named["name"], "Home Fleet")
            saved.assert_called_once()
            for bad in ("", "x" * 61, "bell\x07here"):
                with self.assertRaises(ValueError):
                    setup_state.name_fleet(Path(folder), Path(folder), name=bad)


if __name__ == "__main__":
    unittest.main()
