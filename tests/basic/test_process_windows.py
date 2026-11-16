"""Programs gitSpecOps starts get no window when it has no console (the tray): 2026-11-15."""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from _os.windows import process  # noqa: E402


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class NoWindowTests(unittest.TestCase):
    def test_without_a_console_every_program_starts_without_a_window(self):
        # The tray (pythonw.exe) has no console: each git call used to open a window that took
        # the keyboard, hundreds a minute.
        with patch.object(process, "_has_console", return_value=False):
            self.assertEqual(process.spawn_options(), {"creationflags": subprocess.CREATE_NO_WINDOW})
            self.assertEqual(process.window_options(), {"creationflags": subprocess.CREATE_NO_WINDOW})

    def test_from_a_terminal_programs_share_it_as_before(self):
        with patch.object(process, "_has_console", return_value=True):
            self.assertEqual(process.spawn_options(), {})
            self.assertEqual(process.window_options(), {})

    def test_the_shared_runner_uses_the_options(self):
        from Basic import _run
        with patch.object(process, "_has_console", return_value=False), \
                patch.object(_run.subprocess, "Popen", side_effect=FileNotFoundError) as popen:
            _run.run(["git", "--version"], timeout=5)
        self.assertEqual(popen.call_args.kwargs.get("creationflags"), subprocess.CREATE_NO_WINDOW)


if __name__ == "__main__":
    unittest.main()
