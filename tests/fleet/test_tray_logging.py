"""Pure tray logging/disclosure seams; temporary profiles, no native tray/startup actions.

Native lifecycle is mocked. Raw console output, operational events and explicit key display
must stay independent even when a command fails before the tray can start.
"""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup
setup("sync")

import fleet_tray
from Special._runtime.files import RuntimeIOError
from Special._runtime.logger import configure_logging
from Special._runtime.output import fleet_key_record
from Special._settings.fleet import load_fleet_settings


class TrayLoggingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="tray-logging-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "profile"
        self.home.mkdir()
        self.document = {"schema_version": 2, "components": {"app": {"logging": {"directory": "chosen-logs"}}}}
        self.path = self.home / "settings.json"
        self.save()
        self.arguments = ["--settings-home", str(self.home), "--config-dir", str(self.root / "state"), "run"]

    def save(self):
        self.path.write_text(json.dumps(self.document), encoding="utf-8")

    def test_console_and_notifications_never_copy_raw_text_into_logs(self):
        original = io.StringIO()
        channel = fleet_tray._ConsoleChannel(original)
        key = "ab" * 32
        channel.write("error")
        channel.write(": private-marker " + key + "\n")
        channel.flush()
        self.assertIn(key, original.getvalue())
        self.assertNotIn(key, channel.last_error)
        self.assertNotIn("private-marker", channel.last_error)
        settings, snapshot = fleet_tray._tray_logging_settings(self.arguments)
        log = configure_logging(settings, "app_tray")
        try:
            log.event("peer_stopped", exit_code=1)
        finally:
            log.close()
        saved = (self.home / "chosen-logs/app_tray.log").read_text()
        self.assertIn("peer_stopped", saved)
        self.assertNotIn(key, saved)
        self.assertNotIn("private-marker", saved)
        self.assertFalse((self.root / "state/fleet.log").exists())

    def test_disabled_logging_creates_nothing(self):
        self.document["components"]["app"]["logging"]["enabled"] = False
        self.save()
        settings, snapshot = fleet_tray._tray_logging_settings(self.arguments)
        log = configure_logging(settings, "app_tray")
        log.event("tray_starting")
        log.close()
        self.assertEqual(list(self.home.iterdir()), [self.path])

    def test_invalid_common_settings_never_fall_back_to_legacy_log(self):
        self.path.write_text("invalid")
        with self.assertRaises(ValueError):
            fleet_tray._tray_logging_settings(self.arguments)
        self.assertFalse((self.root / "state").exists())

    def test_known_common_profile_loss_before_start_never_chooses_legacy_defaults(self):
        snapshot = load_fleet_settings(self.home)
        self.path.unlink()
        with patch.object(fleet_tray, "supported", return_value=True), \
             patch.object(fleet_tray, "_run_tray", side_effect=AssertionError("unexpected native tray")):
            with self.assertRaises(ValueError):
                fleet_tray.run_tray(self.arguments, expected_settings=snapshot)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_legacy_only_runtime_defaults_do_not_convert_or_use_state_for_logging(self):
        self.path.unlink()
        settings, snapshot = fleet_tray._tray_logging_settings(self.arguments)
        self.assertIsNone(snapshot)
        self.assertEqual(settings.values["logging"]["directory"], self.home / "logs")
        self.assertEqual(list(self.home.iterdir()), [])

    def test_native_failure_restores_console_and_closes_shared_log(self):
        before = (sys.stdout, sys.stderr)
        with patch.object(fleet_tray, "supported", return_value=True), \
             patch.object(fleet_tray, "_run_tray", side_effect=RuntimeError("synthetic failure")):
            with self.assertRaises(RuntimeError):
                fleet_tray.run_tray(self.arguments)
        self.assertEqual((sys.stdout, sys.stderr), before)
        log = self.home / "chosen-logs/app_tray.log"
        self.assertIn("tray_starting", log.read_text())
        self.assertNotIn("synthetic failure", log.read_text())
        self.assertFalse(log.with_suffix(".log.lock").exists())

    def test_required_log_failure_prevents_native_start_without_alternate_log(self):
        with patch.object(fleet_tray, "supported", return_value=True), \
             patch("Special._runtime.logger.configure_logging", side_effect=RuntimeIOError("logging_setup")), \
             patch.object(fleet_tray, "_run_tray", side_effect=AssertionError("unexpected native tray")):
            with self.assertRaises(RuntimeIOError):
                fleet_tray.run_tray(self.arguments)
        self.assertEqual(list(self.home.iterdir()), [self.path])

    def test_fleet_key_default_is_hidden_and_disclosure_is_explicit(self):
        key = "ab" * 32
        self.assertNotIn(key, json.dumps(fleet_key_record(key)))
        self.assertEqual(fleet_key_record(key, show=True)["fleet_key"], key)
        with self.assertRaises(ValueError):
            fleet_key_record(key, show="yes")


if __name__ == "__main__":
    unittest.main()
