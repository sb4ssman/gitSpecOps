"""Joining a fleet in setup (one machine, 2026-11-16, joined nothing): a key copied over two
lines is collected in parts, anything wrong is asked again, Enter alone does not join."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from _build import setup_walkthrough as walk  # noqa: E402

KEY = "0123456789abcdef" * 4


def answers(*replies):
    return patch.object(walk, "ask", side_effect=list(replies))


class FleetKeyTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(walk, "line")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_whole_key_is_taken(self):
        with answers(f"  {KEY.upper()}  "):
            self.assertEqual(walk._ask_fleet_key(), KEY)

    def test_a_key_over_two_lines_is_collected(self):
        with answers(KEY[:40], KEY[40:]):
            self.assertEqual(walk._ask_fleet_key(), KEY)

    def test_spaces_and_dashes_inside_are_ignored(self):
        with answers("-".join(KEY[i:i + 16] for i in range(0, 64, 16))):
            self.assertEqual(walk._ask_fleet_key(), KEY)

    def test_something_else_is_asked_again(self):
        with answers("Fleet key: " + KEY, KEY):
            self.assertEqual(walk._ask_fleet_key(), KEY)

    def test_too_long_starts_over(self):
        with answers(KEY + "ab", KEY):
            self.assertEqual(walk._ask_fleet_key(), KEY)

    def test_enter_alone_does_not_join(self):
        with answers(""):
            self.assertIsNone(walk._ask_fleet_key())


if __name__ == "__main__":
    unittest.main()
