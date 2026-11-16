"""The app opens the settings folder for the person (2026-11-15); the page never gets the path."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from App._web import setup as routes  # noqa: E402


class OpenSettingsFolderTests(unittest.TestCase):
    def test_the_settings_folder_opens_and_its_path_is_not_returned(self):
        with tempfile.TemporaryDirectory() as home, \
                patch.object(routes, "open_folder") as opened, \
                patch("Special._settings.fleet.fleet_home", return_value=Path(home)):
            result = routes.SetupRoutes(home).act("open-folder", {})
        opened.assert_called_once_with(Path(home))
        self.assertTrue(result["applied"])
        self.assertNotIn(home, str(result))

    def test_a_missing_folder_is_refused_plainly(self):
        with self.assertRaisesRegex(ValueError, "does not exist yet"):
            routes.open_folder(Path(tempfile.gettempdir()) / "no-such-gitspecops-folder")


if __name__ == "__main__":
    unittest.main()
