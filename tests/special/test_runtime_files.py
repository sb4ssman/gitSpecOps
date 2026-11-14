"""Destinations may not run through a planted link; the operating system's own links are fine.

macOS keeps /var, /tmp and /etc behind links to /private; some Linux systems link /home. Those
belong to root, in folders only root can change. A link any user can make is still refused.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from Special._runtime.files import RuntimeIOError, checked_path, system_link, traverses_link  # noqa: E402


class RuntimeFilesTests(unittest.TestCase):
    @unittest.skipIf(os.name != "posix", "symbolic links need privileges on Windows")
    def test_a_link_a_user_made_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            real, link = Path(temp) / "real", Path(temp) / "link"
            real.mkdir()
            link.symlink_to(real, target_is_directory=True)
            self.assertFalse(system_link(link))
            self.assertTrue(traverses_link(link / "settings.json"))
            with self.assertRaises(RuntimeIOError):
                checked_path(link / "settings.json")

    @unittest.skipUnless(sys.platform == "darwin", "macOS keeps /var behind a link to /private/var")
    def test_macos_var_is_the_systems_own_link(self):
        self.assertTrue(Path("/var").is_symlink())
        self.assertTrue(system_link(Path("/var")))
        self.assertFalse(traverses_link(Path("/var/folders/example/settings.json")))

    def test_a_plain_folder_is_fine(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "profile" / "settings.json"
            self.assertFalse(traverses_link(target))
            self.assertEqual(checked_path(target), Path(os.path.abspath(target)))


if __name__ == "__main__":
    unittest.main()
