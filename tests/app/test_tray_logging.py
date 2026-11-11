"""The tray's operational log: counts-only events, chosen by the common app settings.

Temporary profiles only; no tray is started. Raw console text never reaches the log, disabled
logging writes nothing, and invalid common settings never fall back to a legacy location.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from App._tray import qt  # noqa: E402
from Special._runtime.output import fleet_key_record  # noqa: E402


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

    def save(self):
        self.path.write_text(json.dumps(self.document), encoding="utf-8")

    def test_events_are_logged_without_raw_text(self):
        log = qt._logging(self.home)
        try:
            log.event("peer_stopped", exit_code=1)
        finally:
            log.close()
        saved = (self.home / "chosen-logs/app_tray.log").read_text()
        self.assertIn("peer_stopped", saved)
        self.assertNotIn("error:", saved)

    def test_disabled_logging_creates_nothing(self):
        self.document["components"]["app"]["logging"]["enabled"] = False
        self.save()
        log = qt._logging(self.home)
        log.event("tray_starting")
        log.close()
        self.assertEqual(list(self.home.iterdir()), [self.path])

    def test_invalid_common_settings_never_fall_back_to_legacy_log(self):
        self.path.write_text("invalid")
        with self.assertRaises(ValueError):
            qt._logging(self.home)
        self.assertEqual(list(self.home.iterdir()), [self.path])

    def test_legacy_only_profile_uses_documented_defaults_without_converting(self):
        self.path.unlink()
        log = qt._logging(self.home)
        log.close()
        self.assertFalse(self.path.exists(), "logging must never create or convert settings")

    def test_fleet_key_default_is_hidden_and_disclosure_is_explicit(self):
        key = "ab" * 32
        self.assertNotIn(key, json.dumps(fleet_key_record(key)))
        self.assertEqual(fleet_key_record(key, show=True)["fleet_key"], key)
        with self.assertRaises(ValueError):
            fleet_key_record(key, show="yes")


if __name__ == "__main__":
    unittest.main()
