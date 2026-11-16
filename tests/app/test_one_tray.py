"""One tray per profile, and a logged reason when its peer stops (the 2026-11-15 window storm)."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from App._tray.model import GENERIC_FAILURE, KNOWN_FAILURES, failure_code  # noqa: E402
from Special._runtime.logger import COUNTERS  # noqa: E402
from Special._sync.lock import PEER_LOCK, TRAY_LOCK, app_lock  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_build"))


class ReasonCodeTests(unittest.TestCase):
    def test_the_log_gets_a_number_for_why_the_peer_stopped(self):
        self.assertIn("reason", COUNTERS)
        self.assertEqual(failure_code(None), 0)
        self.assertEqual([failure_code(message) for _needles, message in KNOWN_FAILURES],
                         list(range(1, len(KNOWN_FAILURES) + 1)))
        self.assertEqual(failure_code(GENERIC_FAILURE), 9)


class OneTrayTests(unittest.TestCase):
    def test_a_second_tray_cannot_take_the_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            with app_lock(Path(temp), TRAY_LOCK):
                with self.assertRaisesRegex(ValueError, "already running"):
                    app_lock(Path(temp), TRAY_LOCK).__enter__()
                with app_lock(Path(temp), PEER_LOCK):  # the peer's lock is separate
                    pass

    def test_setup_sees_a_running_tray_even_when_its_peer_has_stopped(self):
        import setup_walkthrough as walk
        with tempfile.TemporaryDirectory() as temp, \
                patch("Special._settings.fleet.fleet_directory", return_value=Path(temp)):
            self.assertFalse(walk.app_running())
            with app_lock(Path(temp), TRAY_LOCK):
                self.assertTrue(walk.app_running())
            self.assertFalse(walk.app_running())


if __name__ == "__main__":
    unittest.main()
