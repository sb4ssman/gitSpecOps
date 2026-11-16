"""The app starts on its own: closing the window that started it does not close it (node1,
2026-11-15, twice). Nothing here starts a real app."""
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
    """The fallback: started as a detached child (Linux and macOS always; Windows when WMI refuses)."""
    def setUp(self):
        for name, value in (("running", False), ("_through_windows", None)):
            patcher = patch.object(_detach, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_tray_still_running_after_the_wait_has_started(self):
        with patch.object(_detach.subprocess, "Popen", return_value=Process()) as popen:
            self.assertIn("started", _detach.start(["--web", "loopback"], wait=0))
        argv = popen.call_args.args[0]
        self.assertEqual(argv[1:], [str(_detach.TRAY), "--detached", "--web", "loopback"])

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


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class WindowsStartsItTests(unittest.TestCase):
    """On Windows, Windows itself starts the app (WMI): no window, terminal or setup is its parent."""
    def setUp(self):
        patcher = patch.object(_detach, "running", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_windows_starts_it_and_nothing_is_started_as_a_child(self):
        with patch.object(_detach, "_through_windows", return_value=4321) as through,                 patch.object(_detach, "_exit_code", return_value=None) as exit_code,                 patch.object(_detach.subprocess, "Popen") as popen:
            self.assertEqual(_detach.start(["--web", "loopback"], wait=0), _detach.STARTED)
        self.assertEqual(through.call_args.args[0][1:], [str(_detach.TRAY), "--detached", "--web", "loopback"])
        exit_code.assert_called_once_with(4321, 0)
        popen.assert_not_called()

    def test_when_windows_refuses_it_starts_detached_instead(self):
        with patch.object(_detach, "_through_windows", return_value=None),                 patch.object(_detach.subprocess, "Popen", return_value=Process()) as popen:
            self.assertEqual(_detach.start(wait=0), _detach.STARTED)
        popen.assert_called_once()

    def test_a_second_copy_that_exits_cleanly_means_one_was_running(self):
        with patch.object(_detach, "_through_windows", return_value=4321),                 patch.object(_detach, "_exit_code", return_value=0):
            self.assertEqual(_detach.start(wait=0), _detach.ALREADY)

    def test_settings_overrides_in_the_environment_keep_the_detached_start(self):
        with patch.dict(_detach.os.environ, {"GITSPECOPS_SYNC_HOME": "C:/somewhere"}),                 patch.object(_detach.subprocess, "run") as run:
            self.assertIsNone(_detach._through_windows(["pythonw", "tray.py"]))
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
