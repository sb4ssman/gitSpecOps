"""Proofs cover what they claim, and a clone lands where it was approved (2026-11-17).

Pins (an outside review): a folder the walk could not enter is reported and blocks the
safe-to-wipe verdict; the clone-target check judges the actual target, links included.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from Basic import _discovery  # noqa: E402
from Special._sync.actions import (apply_materialize, every_repository, render_wipe,  # noqa: E402
                                   target_inside_library)


class CoverageTests(unittest.TestCase):
    def test_an_unreadable_folder_is_a_gap_and_blocks_the_verdict(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            subprocess.run(["git", "init", "-q", str(root / "seen")], check=True)
            (root / "locked").mkdir()
            real = os.scandir

            def scandir(path):
                if Path(path).name == "locked":
                    raise PermissionError(13, "Permission denied")
                return real(path)
            with mock.patch.object(_discovery.os, "scandir", scandir):
                gaps = []
                hits = _discovery.find_repos(root, gaps=gaps)
                found, problems = every_repository([root])
            self.assertEqual([Path(hit.path).name for hit in hits], ["seen"])
            self.assertEqual([Path(gap["path"]).name for gap in gaps], ["locked"])
            self.assertEqual([row["action"] for row in problems], ["not_checked"])
            text, safe = render_wipe(problems + [{"path": root / "seen", "name": "seen", "action": "replaceable", "detail": ""}])
            self.assertFalse(safe, "an unchecked folder may hold the only copy of something")
            self.assertIn("NOT SAFE", text)


class TargetTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        self.library, self.outside = self.root / "library", self.root / "outside"
        self.library.mkdir()
        self.outside.mkdir()

    def test_the_actual_target_is_judged(self):
        self.assertTrue(target_inside_library(self.library / "org" / "repo", self.library))
        self.assertFalse(target_inside_library(self.outside / "repo", self.library))
        self.assertFalse(target_inside_library(self.library, self.library), "the library itself is not a target")
        self.assertFalse(target_inside_library(self.library / ".." / "outside" / "repo", self.library))
        self.assertFalse(target_inside_library(self.library / "CON" / "repo", self.library), "a device name")

    def test_a_link_under_the_destination_does_not_lead_outside(self):
        try:
            (self.library / "org").symlink_to(self.outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("links cannot be made here")
        target = self.library / "org" / "repo"
        self.assertFalse(target_inside_library(target, self.library))
        plan = [{"source": target, "name": "repo", "target": target, "library": self.library,
                 "origin": "https://example.invalid/o/repo.git", "action": "clone", "detail": ""}]
        result = apply_materialize(plan)[0]
        self.assertEqual(result["action"], "clone_failed")
        self.assertEqual(list(self.outside.iterdir()), [], "nothing was created outside the library")


if __name__ == "__main__":
    unittest.main()
