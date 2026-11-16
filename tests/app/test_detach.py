"""The app starts on its own: closing the window that started it does not close it (node1,
2026-11-15). Nothing here starts a real app."""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from App import _detach  # noqa: E402


class Process:
    def __init__(self, code=None):
        self.code = code

    def wait(self, timeout):
        if self.code is None:
            raise subprocess.TimeoutExpired("tray", timeout)
        return self.code


class StartTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(_detach, "running", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_tray_still_running_after_the_wait_has_started(self):
        with patch.object(_detach.subprocess, "Popen", return_value=Process()) as popen:
            self.assertIn("started", _detach.start(["--web", "loopback"], wait=0))
        argv = popen.call_args.args[0]
        self.assertEqual(argv[1:], [str(_detach.TRAY), "--foreground", "--web", "loopback"])

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_on_windows_it_leaves_the_callers_job_and_console(self):
        with patch.object(_detach.subprocess, "Popen", return_value=Process()) as popen:
            _detach.start(wait=0)
        flags = popen.call_args.kwargs["creationflags"]
        self.assertTrue(flags & subprocess.DETACHED_PROCESS)
        self.assertTrue(flags & _detach._BREAKAWAY)

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_a_job_that_refuses_breakaway_still_gets_a_start(self):
        with patch.object(_detach.subprocess, "Popen", side_effect=[OSError(5, "denied"), Process()]) as popen:
            self.assertIn("started", _detach.start(wait=0))
        self.assertFalse(popen.call_args.kwargs["creationflags"] & _detach._BREAKAWAY)

    def test_a_tray_that_stops_at_once_says_how_to_see_why(self):
        with patch.object(_detach.subprocess, "Popen", return_value=Process(1)):
            with self.assertRaisesRegex(RuntimeError, "gitso tray --foreground"):
                _detach.start(wait=0)

    def test_a_running_tray_is_not_started_again(self):
        with patch.object(_detach, "running", return_value=True), \
                patch.object(_detach.subprocess, "Popen") as popen:
            self.assertIn("already running", _detach.start(wait=0))
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
