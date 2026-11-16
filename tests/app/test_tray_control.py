"""`gitso tray` while the app runs (the user, 2026-11-16): recent events in words, --follow,
--open at the map, --stop. Nothing here starts or stops a real app."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from App._tray import control  # noqa: E402


class EventWordsTests(unittest.TestCase):
    def test_events_read_as_words(self):
        self.assertTrue(control.event_line({"event": "peer_ready", "timestamp": "2026-11-16T07:19:48+00:00"})
                        .endswith("ready: reading and watching your library"))
        stopped = control.event_line({"event": "peer_stopped", "exit_code": 2,
                                      "timestamp": "2026-11-16T07:40:12+00:00"})
        self.assertIn("with an error (exit code 2", stopped)

    def test_recent_events_come_from_the_log(self):
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / "app_tray.log"
            log.write_text('{"event": "tray_starting", "timestamp": "2026-11-16T07:19:48+00:00"}\nnot json\n',
                           encoding="utf-8")
            with patch.object(control, "log_path", return_value=log):
                self.assertEqual(len(control.recent_events()), 1)


class OpenAndStopTests(unittest.TestCase):
    def test_open_goes_to_the_map(self):
        with patch.object(control, "web_address", return_value="http://127.0.0.1:8760/"), \
                patch.object(control.webbrowser, "open") as browser:
            self.assertEqual(control.open_map(), "http://127.0.0.1:8760/#map")
        browser.assert_called_once_with("http://127.0.0.1:8760/#map")

    def test_open_with_the_web_view_off_says_so(self):
        with patch.object(control, "web_address", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "web view is off"):
                control.open_map()

    def test_stop_leaves_a_request_and_waits_for_the_app_to_go(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch("Special._settings.fleet.fleet_directory", return_value=Path(folder)), \
                    patch("App._detach.running", side_effect=[True, False]):
                self.assertTrue(control.request_stop(wait=5))
            self.assertTrue((Path(folder) / control.QUIT_REQUEST).exists())


if __name__ == "__main__":
    unittest.main()
