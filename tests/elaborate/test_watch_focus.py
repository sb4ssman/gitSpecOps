"""A large drive no longer stops the app (one machine, 2026-11-16): Linux watches only the
repositories and the folders leading to them, and running out of watches leaves the app running
and rereading the library on a timer. Also: the stale wording follows the intervals chosen."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from Elaborate._fleet import events  # noqa: E402
from Elaborate._fleet.display import staleness_text  # noqa: E402


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux's inotify only")
class FocusedWatchTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        self.repo = self.root / "Org" / "project"
        (self.repo / ".git").mkdir(parents=True)
        (self.repo / "src").mkdir()
        for index in range(5):
            (self.root / "Movies" / f"season{index}").mkdir(parents=True)

    def test_only_repositories_and_the_folders_leading_to_them_are_watched(self):
        watcher = events.LinuxEvents([self.root], repositories=[self.repo])
        self.addCleanup(watcher.close)
        watched = set(watcher.paths.values())
        self.assertTrue({self.root, self.root / "Org", self.repo, self.repo / "src"} <= watched)
        self.assertFalse(any("Movies" in path.parts for path in watched))
        self.assertFalse(watcher.incomplete)

    def test_running_out_of_watches_keeps_what_fits_and_says_so(self):
        real, calls = events.LinuxEvents._watch, []

        def limited(watcher, path):
            calls.append(path)
            if len(calls) > 2:
                raise events._WatchLimit(28, "limit")
            real(watcher, path)
        with patch.object(events.LinuxEvents, "_watch", limited):
            watcher = events.LinuxEvents([self.root], repositories=[self.repo])
        self.addCleanup(watcher.close)
        self.assertTrue(watcher.incomplete)
        self.assertEqual(len(watcher.paths), 2)
        self.assertGreaterEqual(watcher.fd, 0)


class StaleWordingTests(unittest.TestCase):
    def test_the_interval_chosen_in_setup_is_named(self):
        text = staleness_text(660, {"tailnet": {"port": 8765, "seconds": 300}})
        self.assertIn("over Tailscale every 5 minutes, as chosen in setup", text)
        self.assertIn("11 minutes", text)

    def test_outside_a_fleet_it_says_so(self):
        self.assertIn("not in a fleet", staleness_text(660, {}))


if __name__ == "__main__":
    unittest.main()
