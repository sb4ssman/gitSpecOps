"""`gitso machine check` on screen: library folder, then the folder inside it, then repositories that
need something (2026-11-15: the wide table wrapped into rows of dashes)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from Special._sync.advice import library_tree  # noqa: E402
from Special._sync.observer import Observation  # noqa: E402


def repo(repo_id, **facts):
    return {"repo_id": repo_id * 32, "branch_id": "b" * 16, "has_upstream": True,
            "upstream_observed_at": None, "ahead": 0, "behind": 0, "staged": 0, "unstaged": 0,
            "untracked": 0, "stashes": 0, "operation": None, **facts}


ROOT = Path("/library")
OBSERVATION = Observation(
    repositories=[repo("a"), repo("b", unstaged=2), repo("c"), repo("d", behind=3)],
    catalog={}, issues=[], branches={"b" * 16: "main"},
    locations=[ROOT / "org-one" / "alpha", ROOT / "org-one" / "beta", ROOT / "org-two" / "gamma",
               ROOT / "loose"])


class LibraryTreeTests(unittest.TestCase):
    def test_folders_are_summarised_and_only_what_needs_something_is_listed(self):
        text = [line for line, _tone in library_tree([ROOT], OBSERVATION)]
        self.assertIn(str(ROOT), text)
        self.assertIn("  org-one  (2 repositories, 1 needs something)", text)
        self.assertIn("  org-two  (1 repository, all clean)", text)
        self.assertTrue(any(line.startswith("      beta  [main]  dirty 2") for line in text))
        self.assertFalse(any("alpha" in line for line in text))
        self.assertIn("  (directly in this folder)  (1 repository, 1 needs something)", text)

    def test_everything_lists_the_clean_ones_too(self):
        text = [line for line, _tone in library_tree([ROOT], OBSERVATION, everything=True)]
        self.assertTrue(any(line.startswith("      alpha  [main]  clean") for line in text))


if __name__ == "__main__":
    unittest.main()
