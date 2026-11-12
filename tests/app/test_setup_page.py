"""The app's setup: the matrix, the setup routes, the setup page's server, and the app loop.

Temporary profiles and invented folders only; servers bind to loopback on a free port. Pins:
every change needs its typed word; the server's loopback, Origin and token checks hold for setup
too; an un-enrolled machine gets the setup page until a library is added; a setup change
restarts the peer; the matrix says honestly what is planned.
"""
import io
import json
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from App._launch import run_app, serve_setup  # noqa: E402
from App._web.server import setup_server  # noqa: E402
from App._web.setup import SetupRoutes  # noqa: E402
from Elaborate._fleet.setup_state import TIERS, setup_state  # noqa: E402


class SetupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="setup-page-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "profile"
        self.home.mkdir()
        (self.home / "settings.json").write_text(json.dumps({"schema_version": 2}), encoding="utf-8")
        self.state_dir = self.root / "state"
        self.library = self.root / "code"
        subprocess.run(["git", "init", "-q", str(self.library / "one")], check=True)
        self.routes = SetupRoutes(self.home, self.state_dir)

    def test_the_matrix_starts_at_this_machine_and_is_honest_about_plans(self):
        state = setup_state(self.home, self.state_dir)
        self.assertIsNone(state["machine"])
        self.assertEqual(state["next"], "machine")
        self.assertEqual([tier["id"] for tier in state["tiers"]],
                         ["installed", "machine", "fleet", "managed_repo", "tailnet"])
        planned = [item["text"] for tier in state["tiers"] for item in tier["unlocks"] if not item["built"]]
        self.assertIn("One privacy policy on every machine", planned)
        self.assertEqual(len(TIERS), 5)

    def test_every_change_needs_its_typed_word(self):
        for action, payload in (("find", {"paths": [str(self.root)]}),
                                ("add", {"paths": [str(self.library)]}),
                                ("join", {"folder": str(self.root)}), ("leave", {})):
            with self.assertRaisesRegex(ValueError, "type [A-Z]+ to allow"):
                self.routes.act(action, {**payload, "confirm": "yes"})
        self.assertIsNone(setup_state(self.home, self.state_dir)["machine"])

    def test_find_add_presentation_join_and_leave(self):
        seen = []
        routes = SetupRoutes(self.home, self.state_dir, on_change=seen.append)
        found = routes.act("find", {"paths": [str(self.root)], "confirm": "LOOK"})["found"]
        self.assertEqual(found[0]["path"], str(self.library.resolve()))
        self.assertIsNone(setup_state(self.home, self.state_dir)["machine"], "looking never enrolls")
        state = routes.act("add", {"paths": [str(self.library)], "confirm": "SCAN"})["state"]
        self.assertEqual(state["machine"]["libraries"], [str(self.library.resolve())])
        self.assertEqual(state["next"], "fleet")
        self.assertTrue(seen and seen[-1]["machine"], "the app hears about the change")
        state = routes.act("presentation", {"face": "window", "web": "off"})["state"]
        self.assertEqual(state["machine"]["presentation"], {"face": "window", "web": "off"})
        synced = self.root / "synced"
        synced.mkdir()
        state = routes.act("join", {"folder": str(synced), "share_names": False, "confirm": "JOIN"})["state"]
        self.assertEqual(list(state["fleet"]["transports"]), ["folder"])
        self.assertFalse(state["fleet"]["share_names"])
        self.assertTrue([tier for tier in state["tiers"] if tier["id"] == "fleet"][0]["reached"])
        state = routes.act("leave", {"confirm": "LEAVE"})["state"]
        self.assertIsNone(state["fleet"])
        self.assertEqual(state["machine"]["libraries"], [str(self.library.resolve())])

    def test_the_setup_server_keeps_the_dashboards_checks(self):
        server, url = setup_server(self.routes, port=0)
        try:
            port = server.server_address[1]
            self.assertTrue(url.endswith(f":{port}/setup"))
            with urllib.request.urlopen(url, timeout=10) as response:
                self.assertIn(b"Grow as you go", response.read())
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/setup", timeout=10) as response:
                token = json.loads(response.read())["local_actions"]["token"]
            origin = f"http://127.0.0.1:{port}"

            def post(body, headers):
                request = urllib.request.Request(f"{origin}/v1/setup/add", data=json.dumps(body).encode(),
                                                 method="POST", headers={"Content-Type": "application/json", **headers})
                try:
                    with urllib.request.urlopen(request, timeout=10) as response:
                        return response.status, json.loads(response.read())
                except urllib.error.HTTPError as exc:
                    return exc.code, json.loads(exc.read() or b"{}")
            body = {"paths": [str(self.library)], "confirm": "SCAN"}
            self.assertEqual(post(body, {"Origin": origin})[0], 403, "no token, no change")
            self.assertEqual(post(body, {"Origin": "http://elsewhere", "X-GitSpecOps-Token": token})[0], 403)
            status, refused = post({**body, "confirm": "scan"}, {"Origin": origin, "X-GitSpecOps-Token": token})
            self.assertEqual(status, 400)
            self.assertIn("type SCAN", refused["error"], "a refusal says why")
            status, result = post(body, {"Origin": origin, "X-GitSpecOps-Token": token})
            self.assertEqual(status, 200)
            self.assertTrue(result["state"]["machine"])
        finally:
            server.shutdown()
            server.server_close()

    def test_an_unenrolled_machine_gets_setup_until_a_library_is_added(self):
        stopping, urls, outcome = threading.Event(), [], {}

        def run():
            outcome["enrolled"] = serve_setup(self.state_dir, self.home, stopping=stopping,
                                              on_setup=urls.append, port=0)
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        for _ in range(100):
            if urls:
                break
            threading.Event().wait(0.05)
        self.assertTrue(urls and urls[0].endswith("/setup"))
        SetupRoutes(self.home, self.state_dir).act("add", {"paths": [str(self.library)], "confirm": "SCAN"})
        # The page's own routes notice; here the change came from outside, so stop explicitly.
        stopping.set()
        thread.join(timeout=10)
        self.assertFalse(thread.is_alive())

    def test_the_app_loop_restarts_the_peer_when_setup_changes_something(self):
        SetupRoutes(self.home, self.state_dir).act("add", {"paths": [str(self.library)], "confirm": "SCAN"})
        app_stopping, runs, routes = threading.Event(), [], []

        def fake_server(port, setup=None):
            routes.append(setup)
            return lambda *args: (None, None)

        def fake_peer(argv, stopping=None, on_ready=None, serve=None):
            runs.append(argv)
            if len(runs) == 1:
                # A change made from the web view, through the routes the peer was handed.
                routes[-1].act("presentation", {"face": "web", "web": "loopback"})
                self.assertTrue(stopping.wait(5), "the change must stop this run of the peer")
                return 0
            app_stopping.set()
            return 0
        with patch("App._launch.peer_server", side_effect=fake_server), \
                patch("Elaborate._fleet.cli.main", side_effect=fake_peer), redirect_stdout(io.StringIO()):
            code = run_app(self.state_dir, self.home, stopping=app_stopping)
        self.assertEqual(code, 0)
        self.assertEqual(len(runs), 2, "the peer starts again with the changed setup")

    def test_quitting_while_unenrolled_ends_the_app(self):
        stopping = threading.Event()
        stopping.set()
        self.assertEqual(run_app(self.state_dir, self.home, stopping=stopping), 0)


if __name__ == "__main__":
    unittest.main()
