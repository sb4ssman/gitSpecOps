"""The App & setup tab changes this machine's setup (the user, 2026-11-16): connections and their
interval, the fetch schedule, start at sign-in, joining through a machine on Tailscale, showing
the fleet key. Temporary profiles only; start at sign-in and Tailscale are stood in for."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from App._web.setup import SetupRoutes  # noqa: E402
from Elaborate._fleet.setup_state import setup_state  # noqa: E402

KEY = "ab" * 32


class SetupControlsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="setup-controls-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "profile"
        self.home.mkdir()
        (self.home / "settings.json").write_text(json.dumps({"schema_version": 2}), encoding="utf-8")
        self.state_dir = self.root / "state"
        self.library = self.root / "code"
        subprocess.run(["git", "init", "-q", str(self.library / "one")], check=True)
        self.synced = self.root / "synced"
        self.synced.mkdir()
        self.changes = []
        self.routes = SetupRoutes(self.home, self.state_dir, on_change=self.changes.append)
        self.approved("add", {"paths": [str(self.library)]})
        patcher = patch("Elaborate._fleet.autostart.status",
                        return_value={"supported": True, "enabled": False, "elsewhere": None})
        patcher.start()
        self.addCleanup(patcher.stop)

    def approved(self, action, payload):
        plan = self.routes.act(action, payload)
        self.assertFalse(plan["applied"], plan)
        return self.routes.act(action, {**payload, "apply": plan["plan_id"]})

    def transports(self):
        return (setup_state(self.home, self.state_dir)["fleet"] or {}).get("transports") or {}

    def test_settings_read_back_without_the_key(self):
        settings = self.routes.act("settings", {})["settings"]
        self.assertTrue(settings["enrolled"])
        self.assertIsNone(settings["fleet_id"])
        self.assertEqual(settings["connections"]["tailnet"]["choices"], [60, 300, 1800])
        self.assertNotIn("fleet_secret", json.dumps(settings))

    def test_turning_on_a_connection_starts_a_fleet_and_shows_the_plan_first(self):
        plan = self.routes.act("connections", {"folder": str(self.synced)})
        self.assertFalse(plan["applied"])
        self.assertIn("start the fleet My fleet", plan["plan"]["changes"][0])
        self.assertEqual(self.transports(), {})
        self.routes.act("connections", {"folder": str(self.synced), "apply": plan["plan_id"]})
        self.assertEqual(Path(self.transports()["folder"]["path"]), self.synced.resolve())
        self.assertTrue(self.changes, "the app is told, so it reconnects")

    def test_connections_change_and_turn_off(self):
        self.approved("connections", {"folder": str(self.synced), "tailnet": True, "tailnet_seconds": 300})
        self.assertEqual(set(self.transports()), {"folder", "tailnet"})
        self.approved("connections", {"folder": "", "tailnet": True, "tailnet_seconds": 1800})
        self.assertEqual(set(self.transports()), {"tailnet"})
        self.assertEqual(self.transports()["tailnet"]["seconds"], 1800)
        self.approved("connections", {"tailnet": False})
        self.assertEqual(self.transports(), {}, "no connection left: the machine leaves the fleet")

    def test_an_interval_setup_does_not_offer_is_refused(self):
        with self.assertRaisesRegex(ValueError, "1, 5 or 30 minutes"):
            self.routes.act("connections", {"tailnet": True, "tailnet_seconds": 7})

    def test_fetch_schedule(self):
        self.routes.act("fetch", {"minutes": 360})
        self.assertEqual(self.routes.act("settings", {})["settings"]["fetch_minutes"], 360)
        with self.assertRaises(ValueError):
            self.routes.act("fetch", {"minutes": 5})

    def test_start_at_sign_in_uses_the_tray(self):
        with patch("Elaborate._fleet.autostart.enable") as enable:
            self.routes.act("sign-in", {"enabled": True})
        self.assertTrue(str(enable.call_args.kwargs["script"]).endswith(str(Path("App") / "tray.py")))
        with patch("Elaborate._fleet.autostart.disable") as disable:
            self.routes.act("sign-in", {"enabled": False})
        disable.assert_called_once()

    def test_the_key_is_shown_only_after_its_plan_is_approved(self):
        first = self.routes.act("show-key", {})
        self.assertNotIn("key", first)
        shown = self.routes.act("show-key", {"apply": first["plan_id"]})
        self.assertEqual(len(shown["key"]), 64)

    def test_sealing_shows_the_install_in_its_plan_and_installs_only_on_apply(self):
        self.approved("connections", {"folder": str(self.synced)})
        with patch("Elaborate._fleet.sealed.venv_has", return_value=False), \
                patch("Elaborate._fleet.sealed.install", return_value="installed") as install:
            plan = self.routes.act("seal", {"enabled": True})
            self.assertTrue(any("install" in line for line in plan["plan"]["changes"]))
            install.assert_not_called()
            self.routes.act("seal", {"enabled": True, "apply": plan["plan_id"]})
            install.assert_called_once()
        self.assertTrue(self.routes.act("settings", {})["settings"]["shared"]["sealed"])

    def test_a_question_from_another_machine_is_answered_here(self):
        from Special._security._policy_edit import policy_view
        self.approved("connections", {"folder": str(self.synced)})
        settings = self.routes.act("settings", {})["settings"]
        config = self.routes._config()
        shared = self.routes._shared(config)
        shared.receive({"schema": 1, "fleet_id": shared.fleet_id, "machine_id": "desk", "label": "desk",
                        "lists": {"safe_values": ["example.invalid"]}, "removed": {}})
        questions = self.routes.act("settings", {})["settings"]["shared"]["questions"]
        self.assertEqual(len(questions), 1)
        self.assertEqual(settings["shared"]["questions"], [])
        self.routes.act("shared-answer", {"id": questions[0]["id"], "accept": True})
        self.assertIn("example.invalid", policy_view(self.home)["lists"]["safe_values"])

    def test_joining_a_fleet_by_its_name_on_tailscale(self):
        named = {"name": "Home-Fleet", "at": "2026-11-16T10:00:00+00:00"}
        with patch.object(SetupRoutes, "_key_from_fleet", return_value=(KEY, named)) as handed:
            joined = self.approved("join", {"fleet_id": "f" * 16, "fleet_label": "Home-Fleet",
                                            "tailnet": True, "tailnet_seconds": 300})
        handed.assert_called_once_with("f" * 16)
        self.assertNotIn(KEY, json.dumps(joined))
        self.assertIn("tailnet", self.transports())
        self.assertEqual(self.routes.act("settings", {})["settings"]["fleet_name"], "Home-Fleet")

    def test_renaming_the_fleet(self):
        self.approved("connections", {"folder": str(self.synced), "fleet_name": "First"})
        self.assertEqual(self.routes.act("settings", {})["settings"]["fleet_name"], "First")
        self.routes.act("name-fleet", {"name": "  Home   Fleet "})
        self.assertEqual(self.routes.act("settings", {})["settings"]["fleet_name"], "Home Fleet")
        with self.assertRaises(ValueError):
            self.routes.act("name-fleet", {"name": ""})


if __name__ == "__main__":
    unittest.main()
